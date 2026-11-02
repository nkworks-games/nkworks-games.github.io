# scene_check.py — Blenderシーンの「めり込み・浮き・すり抜け・カメラ埋まり」を全フレーム調べる
# （blender-video-physics-guard の点検スクリプト。並行地球で足した検査には「並行地球：」と書いてある）
#   並行地球：shots.py --build-only で保存した cutNNN.blend を点検する。まとめて回すのは check_shots.py
# 使い方: blender -b scene.blend -P scene_check.py -- [--step 2] [--shots 12] [--out check_out]
#   Mac: /Applications/Blender.app/Contents/MacOS/Blender -b scene.blend -P scene_check.py -- --shots 12
# 結果: check_out/report.json（ok: true/false）と、問題フレーム＋等間隔フレームの確認画像 check_out/sheet.png
import bpy, bmesh, sys, os, json, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

# ===== [SEC:CONFIG] =====（シーンごとに変えるのはここだけ。許容をゆるめて OK にするのは禁止）
CONFIG = dict(
    STEP=4,                # 何フレームごとに調べるか（速い動き・接触が多い場面は 1）
    TOL=0.01,              # めり込みの許容 (m)。1〜2cm を超えると目に見える
    FLOAT_TOL=0.02,        # 地面に接しているべき物の浮きの許容 (m)
    FLOOR_MAX_DEPTH=0.5,   # これより深い「床の下」は別の階など。床抜け判定の範囲 (m)
    FLOORS=[],             # 床・地面の名前。空なら名前に floor/ground/地面/床 を含む物か、カスタムプロパティ floor=True
    GROUNDED=[],           # 地面に接しているべき物（家具・立っている人など）。カスタムプロパティ grounded=True でも可
    IGNORE_PAIRS=[],       # わざと重ねている組 例 [("Hand.R", "Cup")]
    SUBJECTS=[],           # カメラに映っているべき物（主役）。カスタムプロパティ subject=True でも可
    FEET=[],               # 足すべり検査 例 [("Armature", "foot.L"), ("Armature", "foot.R")]
    FOOT_PLANT_H=0.03,     # 足が床からこの高さ以下なら「接地中」
    FOOT_SLIDE=0.02,       # 接地中に1サンプルで横に動いてよい距離 (m)
    MAX_SPEED=2.0,         # 1フレームに動いてよい距離 (m)。超えたら瞬間移動の疑い
    CAM_MIN_DIST=0.05,     # カメラと一番近い面の最小距離 (m)
    MAX_VERTS=4000,        # めり込みの深さを測る頂点数の上限（多い物は間引く）
    SAME_ROOT_OK=True,     # 同じ親（同じ素材の部品どうし。目と頭など）の重なりは調べない
    MAX_SHOTS_PROBLEM=6,   # 確認画像に入れる問題フレームの数
)
# =====

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
def arg(name, default):
    return type(default)(argv[argv.index(name) + 1]) if name in argv else default
blend = next((a for a in argv if a.endswith(".blend")), None)
if blend and bpy.data.filepath != os.path.abspath(blend):
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(blend))
CONFIG["STEP"] = arg("--step", CONFIG["STEP"])
SHOTS = arg("--shots", 12)
OUT = os.path.abspath(arg("--out", "check_out"))
os.makedirs(OUT, exist_ok=True)

sc = bpy.context.scene
cam = sc.camera
def prop(o, k): return bool(o.get(k, False))
def root(o):
    while o.parent: o = o.parent
    return o
def renders(o): return not o.hide_render and not prop(o, "nocheck")
meshes = [o for o in sc.objects if o.type == "MESH" and renders(o)]
is_floor = lambda o: o.name in CONFIG["FLOORS"] or prop(o, "floor") or (not CONFIG["FLOORS"] and any(k in o.name.lower() for k in ("floor", "ground", "地面", "床")))
floors = [o for o in meshes if is_floor(o)]
solids = [o for o in meshes if o not in floors]
grounded = [o for o in solids if o.name in CONFIG["GROUNDED"] or prop(o, "grounded")]
subjects = [o for o in sc.objects if o.name in CONFIG["SUBJECTS"] or prop(o, "subject")]
ignore = {frozenset(p) for p in CONFIG["IGNORE_PAIRS"]}

problems, warnings = [], []
def add(lst, frame, kind, msg, where=None):
    seen = {(p["kind"], p["msg"]) for p in lst}
    vis = None
    if where is not None and cam:
        v = world_to_camera_view(sc, cam, Vector(where))
        vis = bool(0 <= v.x <= 1 and 0 <= v.y <= 1 and v.z > 0)
    if (kind, msg) not in seen:  # 同じ問題は最初のフレームだけ記録し、続くフレーム数を数える
        lst.append(dict(frame=frame, kind=kind, msg=msg, in_camera=vis, frames=1, last=frame, worst=frame))
    else:
        for p in lst:
            if (p["kind"], p["msg"]) == (kind, msg): p["frames"] += 1; p["last"] = frame; p["in_camera"] = p["in_camera"] or vis

# ===== [SEC:STATIC] =====（フレームに関係ない問題を1回だけ調べる）
for o in meshes:
    s = o.matrix_world.to_scale()
    if min(s) < 0: add(warnings, None, "負のスケール", f"{o.name}: スケールがマイナス（面が裏返る）。Ctrl+A で適用する")
    elif max(s) / max(min(s), 1e-9) > 1.001 or abs(s.x - 1) > 0.001:
        if o.type == "MESH" and (o.rigid_body or any(m.type in ("CLOTH", "COLLISION") for m in o.modifiers)):
            add(problems, None, "スケール未適用", f"{o.name}: 物理を使うのにスケール {tuple(round(x,3) for x in s)} が未適用（判定がずれる）")
    bm = bmesh.new(); bm.from_mesh(o.data)
    if bm.verts:
        closed = all(e.is_manifold for e in bm.edges)
        if closed and bm.calc_volume(signed=True) < 0:
            add(warnings, None, "法線が裏", f"{o.name}: 面の向きが内側（法線を外側に再計算する）")
    bm.free()
for img in bpy.data.images:
    if img.source == "FILE" and img.users and not img.packed_file and not os.path.exists(bpy.path.abspath(img.filepath)):
        add(problems, None, "テクスチャなし", f"画像 {img.name} のファイルが無い（ピンク色で映る）: {img.filepath}")
rbw = sc.rigidbody_world
if rbw and getattr(rbw, "substeps_per_frame", 10) < 10:
    add(warnings, None, "物理の刻み", f"リジッドボディの substeps_per_frame={rbw.substeps_per_frame}（10以上、速い物は20以上）")
for o in meshes:
    for m in o.modifiers:
        if m.type == "CLOTH":
            if m.settings.quality < 8: add(warnings, None, "布の品質", f"{o.name}: 布の quality={m.settings.quality}（8以上）")
            if not m.collision_settings.use_self_collision: add(warnings, None, "布の自己衝突", f"{o.name}: 布の自己衝突がオフ（布どうしがすり抜ける）")
if not cam: add(problems, None, "カメラなし", "シーンにカメラが無い")

# ===== [SEC:HELPERS] =====
deps = bpy.context.evaluated_depsgraph_get()
def world_mesh(o):
    """評価後（アニメ・モディファイア・アーマチュア適用後）のワールド座標の頂点と三角形"""
    ev = o.evaluated_get(deps); me = ev.to_mesh()
    mw = ev.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    me.calc_loop_triangles()
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    closed = len(me.edges) > 0 and all(c == 2 for c in _edge_face_counts(me))
    ev.to_mesh_clear()
    return verts, tris, closed
def _edge_face_counts(me):
    cnt = {}
    for p in me.polygons:
        for k in p.edge_keys: cnt[k] = cnt.get(k, 0) + 1
    return [cnt.get(e.key, 0) for e in me.edges]
def aabb(vs):
    xs, ys, zs = zip(*vs) if vs else ((0,), (0,), (0,))
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))
def aabb_hit(a, b, pad=0.0):
    return all(a[0][i] - pad <= b[1][i] and b[0][i] - pad <= a[1][i] for i in range(3))
def sample(vs):
    step = max(1, len(vs) // CONFIG["MAX_VERTS"]); return vs[::step]
def _crossings(tree, o, d, maxn=64):
    """並行地球：o から d の向きに、面を何回横切るか"""
    n = 0
    for _ in range(maxn):
        h = tree.ray_cast(o, d)
        if h[0] is None: break
        n += 1; o = h[0] + d * 1e-4
    return n
_DIRS = [Vector((0.267, 0.534, 0.802)).normalized(), Vector((-0.71, 0.31, -0.63)).normalized(), Vector((0.12, -0.93, 0.35)).normalized()]
def inside(tree, v):
    """並行地球：閉じた形の内側か。3つの向きに光線を打ち、横切る回数が奇数の向きが多ければ内側
    （一番近い面の向きだけで決めると、くぼみや細かい部品の多い形で外側の点を内側と間違える）"""
    return sum(_crossings(tree, v, d) % 2 for d in _DIRS) >= 2
def depth_into(vs, tree, closed):
    """vs の頂点が tree の中にどれだけ深く入っているか（閉じた形だけ測れる）"""
    if not closed: return 0.0, None
    best, at = 0.0, None
    for v in sample(vs):
        loc, nrm, _, d = tree.find_nearest(v)
        if loc is not None and (v - loc).dot(nrm) < 0 and d > best and inside(tree, v): best, at = d, v
    return best, at
def floor_depth(vs, ftree):
    """床より下に出ている深さ（真上に床の表側がある頂点）"""
    best, at = 0.0, None
    for v in sample(vs):
        hit = ftree.ray_cast(v, Vector((0, 0, 1)), CONFIG["FLOOR_MAX_DEPTH"])
        if hit[0] is not None and hit[1].z > 0.2 and hit[3] > best: best, at = hit[3], v
    return best, at
def floor_gap(vs, ftrees):
    """一番低い点から下の床までの距離（浮き）"""
    lo = min(vs, key=lambda v: v.z)
    gaps = [h[3] for t in ftrees for h in [t.ray_cast(lo + Vector((0, 0, 0.001)), Vector((0, 0, -1)), 100)] if h[0] is not None]
    return (min(gaps) - 0.001) if gaps else None, lo

# ===== [SEC:FRAMES] =====
prev_center, prev_feet = {}, {}
prev_soles = {}
def animated(o):
    """並行地球：動く物か（自分・親のアニメーション、形のキーのアニメーション）"""
    x = o
    while x:
        if x.animation_data and x.animation_data.action: return True
        if x.type == "MESH" and x.data.shape_keys and x.data.shape_keys.animation_data: return True
        x = x.parent
    return False
static_cache = {}
frames = list(range(sc.frame_start, sc.frame_end + 1, CONFIG["STEP"]))
if frames[-1] != sc.frame_end: frames.append(sc.frame_end)
for f in frames:
    sc.frame_set(f); deps = bpy.context.evaluated_depsgraph_get()
    data = {}
    for o in meshes:
        if o in static_cache:
            data[o] = static_cache[o]; continue
        vs, tris, closed = world_mesh(o)
        if not vs: continue
        if any(math.isnan(c) or abs(c) > 1e6 for v in vs[:50] for c in v):
            add(problems, f, "座標がおかしい", f"{o.name}: 座標が NaN か巨大"); continue
        data[o] = dict(vs=vs, tris=tris, closed=closed, box=aabb(vs), tree=None)
        if not animated(o) and (o.type != "MESH" or not any(m.type == "PARTICLE_SYSTEM" for m in o.modifiers)):
            static_cache[o] = data[o]
    def tree(o):
        d = data[o]
        if d["tree"] is None: d["tree"] = BVHTree.FromPolygons(d["vs"], d["tris"], epsilon=0.0)
        return d["tree"]
    # 物どうしのめり込み・完全に埋まっている
    objs = [o for o in solids if o in data]
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            if frozenset((a.name, b.name)) in ignore: continue
            if CONFIG["SAME_ROOT_OK"] and root(a) == root(b) and (a.parent or b.parent): continue
            if not aabb_hit(data[a]["box"], data[b]["box"]): continue
            pairs = tree(a).overlap(tree(b))
            da, pa = depth_into(data[a]["vs"], tree(b), data[b]["closed"])
            db, pb = depth_into(data[b]["vs"], tree(a), data[a]["closed"])
            d, at = (da, pa) if da >= db else (db, pb)
            if d > CONFIG["TOL"]:
                kind = "めり込み" if pairs else "埋まっている"
                add(problems, f, kind, f"{a.name} と {b.name}", at)
                p = next(p for p in problems if p["msg"] == f"{a.name} と {b.name}")
                if d * 100 > p.get("depth_cm", 0): p["depth_cm"], p["worst"] = round(d * 100, 1), f
            elif pairs and not (data[a]["closed"] and data[b]["closed"]):
                add(warnings, f, "面が交差", f"{a.name} と {b.name}（閉じていない形なので深さは測れない。目で確認）", data[a]["vs"][0])
    # 床抜け・浮き
    ftrees = [tree(o) for o in floors if o in data]
    for o in objs:
        for ft in ftrees:
            d, at = floor_depth(data[o]["vs"], ft)
            if d > CONFIG["TOL"] + float(o.get("embed_ok", 0.0)):
                add(problems, f, "床にめり込み", f"{o.name}", at)
                p = next(p for p in problems if p["msg"] == o.name and p["kind"] == "床にめり込み")
                if d * 100 > p.get("depth_cm", 0): p["depth_cm"], p["worst"] = round(d * 100, 1), f
        if o in grounded and ftrees:
            g, lo = floor_gap(data[o]["vs"], ftrees)
            if "sole_L" in o.keys() and o.get("pose") not in ("sit", "paddle"):  # 並行地球：立つ・歩く人は、どちらかの足の裏が地面についていればよい
                gs = []
                for sd in ("L", "R"):
                    for i in list(o.get("sole_" + sd, []))[::4]:
                        v = data[o]["vs"][i]
                        for ft in ftrees:
                            h = ft.ray_cast(v + Vector((0, 0, 0.5)), Vector((0, 0, -1)), 10)
                            if h[0] is not None: gs.append(v.z - h[0].z)
                if gs: g, lo = max(0.0, min(gs)), lo
            else:  # 並行地球：かたい物は、下の方（一番低い点から20cm）のどこかが地面に触れていれば「置かれている」
                vs_ = data[o]["vs"]; lo_z = min(v.z for v in vs_)
                low = [v for v in sample(vs_) if v.z < lo_z + 0.2]
                gs = [v.z - h[0].z for v in low for ft in ftrees for h in [ft.ray_cast(v + Vector((0, 0, 0.5)), Vector((0, 0, -1)), 10)] if h[0] is not None]
                if gs: g = max(0.0, min(gs))
            if g is not None and g > CONFIG["FLOAT_TOL"]: add(problems, f, "浮いている", f"{o.name}（{round(g*100,1)}cm）", lo)
    # 瞬間移動
    for o in objs:
        c = (data[o]["box"][0] + data[o]["box"][1]) / 2
        if o in prev_center and (c - prev_center[o][0]).length / max(1, f - prev_center[o][1]) > CONFIG["MAX_SPEED"]:
            add(problems, f, "瞬間移動", f"{o.name}: 1フレームで {round((c - prev_center[o][0]).length / max(1, f - prev_center[o][1]), 2)}m 動いた", c)
        prev_center[o] = (c, f)
    # 足すべり
    for arm_name, bone in CONFIG["FEET"]:
        arm = sc.objects.get(arm_name); pb = arm and arm.pose.bones.get(bone)
        if not pb: add(warnings, None, "足の設定", f"{arm_name}/{bone} が見つからない"); continue
        p = arm.matrix_world @ pb.head
        g = None
        for ft in ftrees:
            h = ft.ray_cast(p + Vector((0, 0, 0.5)), Vector((0, 0, -1)), 10)
            if h[0] is not None: g = p.z - h[0].z if g is None else min(g, p.z - h[0].z)
        planted = g is not None and g < CONFIG["FOOT_PLANT_H"]
        key = (arm_name, bone)
        if planted and key in prev_feet and prev_feet[key][1]:
            mv = (p.xy - prev_feet[key][0].xy).length
            if mv > CONFIG["FOOT_SLIDE"]: add(problems, f, "足すべり", f"{arm_name}/{bone}（接地中に{round(mv*100,1)}cm動いた）", p)
        prev_feet[key] = (p.copy(), planted)
    # 並行地球：形のキーで歩く・こぐ人の足すべり（足の裏の頂点の平均で）
    for o in objs:
        if "cycle" not in o.keys() or o.get("in_boat"): continue
        for sd in ("L", "R"):
            ids = list(o.get("sole_" + sd, []))
            if not ids: continue
            vs = data[o]["vs"]; p = sum((vs[i] for i in ids), Vector()) / len(ids)
            # 接地中＝足の裏全体（かかとから指の付け根まで）が地面から FOOT_PLANT_H 以内。
            # 骨のある人で「足首の高さ」で決めるのと同じ考え（かかとが上がり始めたら接地中ではない）
            gs_ = []
            for i in ids[::4]:
                v = vs[i]
                for ft in ftrees:
                    h = ft.ray_cast(v + Vector((0, 0, 0.5)), Vector((0, 0, -1)), 10)
                    if h[0] is not None: gs_.append(v.z - h[0].z)
            g = max(gs_) if gs_ else None
            planted = g is not None and g < CONFIG["FOOT_PLANT_H"]
            key = (o.name, sd)
            if planted and key in prev_soles and prev_soles[key][1]:
                mv = (p.xy - prev_soles[key][0].xy).length
                if mv > CONFIG["FOOT_SLIDE"]: add(problems, f, "足すべり", f"{o.name} の{'左' if sd == 'L' else '右'}足（接地中に{f - prev_soles[key][2]}フレームで{round(mv*100,1)}cm動いた）", p)
            prev_soles[key] = (p.copy(), planted, f)
    # カメラ
    if cam:
        cp = cam.matrix_world.translation
        for o in objs + [o for o in floors if o in data]:
            if not aabb_hit((cp, cp), data[o]["box"], CONFIG["CAM_MIN_DIST"] + cam.data.clip_start): continue
            loc, nrm, _, d = tree(o).find_nearest(cp)
            if loc is None: continue
            if data[o]["closed"] and (cp - loc).dot(nrm) < 0: add(problems, f, "カメラが中", f"カメラが {o.name} の中にある")
            elif d < max(CONFIG["CAM_MIN_DIST"], cam.data.clip_start): add(problems, f, "カメラが近すぎ", f"カメラと {o.name} が {round(d*100,1)}cm（面が切れて見える）")
        for ft, fo in [(tree(o), o) for o in floors if o in data]:
            h = ft.ray_cast(cp, Vector((0, 0, 1)), 1.0e5)
            if h[0] is not None and h[1].z > 0:  # 上へ打って、上向きの面（地面の表）に下から当たる＝地面の下
                add(problems, f, "カメラが地面の下", f"カメラが {fo.name} の下にある（{round(h[3], 2)}m 下）")
        for o in subjects:
            corners = [o.matrix_world @ Vector(c) for c in o.bound_box] if o.type != "EMPTY" else [o.matrix_world.translation]
            vv = [world_to_camera_view(sc, cam, c) for c in corners]
            inside = [0 <= v.x <= 1 and 0 <= v.y <= 1 and v.z > 0 for v in vv]
            if not any(inside): add(problems, f, "主役が映っていない", o.name)
            elif not all(inside): add(warnings, f, "主役が画面の端で切れている", o.name)

# ===== [SEC:SHOTS] =====（問題フレーム＋等間隔フレームを Workbench で軽くレンダーし、1枚の確認画像にする）
shot_files = []
if SHOTS and cam:
    bad = [p["worst"] for p in sorted(problems, key=lambda p: p["in_camera"] is False) if p["worst"] is not None]
    want = sorted(set(bad[:CONFIG["MAX_SHOTS_PROBLEM"]] + [round(sc.frame_start + i * (sc.frame_end - sc.frame_start) / max(1, SHOTS - 1)) for i in range(SHOTS)]))
    r = sc.render; keep = (r.engine, r.resolution_percentage, r.filepath, r.image_settings.file_format)
    vl = bpy.context.view_layer; keep_ov = vl.material_override; keep_spp = sc.cycles.samples if hasattr(sc, "cycles") else None
    try:
        r.engine = "BLENDER_WORKBENCH"; r.resolution_percentage = 25; r.image_settings.file_format = "PNG"
        sh = sc.display.shading; sh.show_xray = False; sh.color_type = "RANDOM"  # 物ごとに色を変えて重なりを見やすく
        if os.environ.get("CHECK_ENGINE", "").upper() == "CYCLES":
            # 並行地球：GPU（OpenGL）の無い所では Workbench が非常に遅いので、Cycles を少ない回数で使い、
            # 物ごとに乱数の色を塗る材質で上書きする（Workbench の RANDOM と同じ見え方）
            m = bpy.data.materials.new("点検用の色"); nt = m.node_tree
            for n in list(nt.nodes): nt.nodes.remove(n)
            oi = nt.nodes.new("ShaderNodeObjectInfo"); hsv = nt.nodes.new("ShaderNodeCombineColor"); hsv.mode = "HSV"
            nt.links.new(oi.outputs["Random"], hsv.inputs[0]); hsv.inputs[1].default_value = 0.6; hsv.inputs[2].default_value = 0.8
            df = nt.nodes.new("ShaderNodeBsdfDiffuse"); nt.links.new(hsv.outputs[0], df.inputs["Color"])
            o_ = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(df.outputs[0], o_.inputs["Surface"])
            vl.material_override = m
            r.engine = "CYCLES"; sc.cycles.samples = 8; sc.cycles.use_denoising = True
            # 煙などの「体積だけ」の材質は、上書きすると不透明な箱になって奥が見えなくなるので、確認画像の間だけ描かない
            def volume_only(o):
                ms = [sl.material for sl in o.material_slots if sl.material and sl.material.node_tree]
                if not ms: return False
                for mt in ms:
                    outs = [n for n in mt.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]
                    if not outs or outs[0].inputs["Surface"].is_linked or not outs[0].inputs["Volume"].is_linked: return False
                return True
            hidden_vol = [o for o in sc.objects if o.type == "MESH" and not o.hide_render and volume_only(o)]
            for o in hidden_vol: o.hide_render = True
        for k in dir(r):
            if k.startswith("use_stamp_") and isinstance(getattr(r, k), bool): setattr(r, k, k == "use_stamp_frame")
        r.use_stamp = True; r.stamp_font_size = 20  # フレーム番号を焼き込む
        for f in want:
            sc.frame_set(f); r.filepath = os.path.join(OUT, f"f{f:05d}.png")
            bpy.ops.render.render(write_still=True); shot_files.append(r.filepath)
    except Exception as e:
        warnings.append(dict(frame=None, kind="確認画像", msg=f"レンダーできなかった: {e}"))
    finally:
        r.engine, r.resolution_percentage, r.filepath, r.image_settings.file_format = keep; r.use_stamp = False
        vl.material_override = keep_ov
        for o in locals().get("hidden_vol", []): o.hide_render = False
        if keep_spp is not None: sc.cycles.samples = keep_spp
    if shot_files:
        cols = 4; rows = math.ceil(len(shot_files) / cols)
        lst = os.path.join(OUT, "list.txt")
        sheet = os.path.join(OUT, "sheet.png")
        with open(lst, "w") as fh:
            for p in shot_files: fh.write(f"file '{p}'\n")
        os.system(f'ffmpeg -y -loglevel error -f concat -safe 0 -i "{lst}" -vf "scale=480:-2,tile={cols}x{rows}:padding=4" -frames:v 1 "{sheet}"')

# ===== [SEC:REPORT] =====
report = dict(
    ok=not problems,
    checked=dict(frames=f"{sc.frame_start}-{sc.frame_end} を {CONFIG['STEP']} フレームごと", objects=len(solids), floors=[o.name for o in floors],
                 grounded=[o.name for o in grounded], subjects=[o.name for o in subjects]),
    problems=sorted(problems, key=lambda p: (p["in_camera"] is False, p["frame"] or 0)),
    warnings=warnings,
    shots=[os.path.relpath(p) for p in shot_files] + ([os.path.relpath(os.path.join(OUT, "sheet.png"))] if os.path.exists(os.path.join(OUT, "sheet.png")) else []),
)
with open(os.path.join(OUT, "report.json"), "w") as fh: json.dump(report, fh, ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))
sys.exit(0 if report["ok"] else 1) if bpy.app.background or "--exit" in argv else None
