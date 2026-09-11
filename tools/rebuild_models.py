"""
重新生成模型。改了 tools/blender/build_swordman.py 之后跑这个。

**只有改模型（比例 / 配色 / 形状）才需要跑**；改代码、改数值、改关卡都不用。

它做两件事，第二步不能省 —— 非编辑器模式不会重新导入 glb，
少了它游戏里会一直用旧模型：
  1) Blender 无头导出 assets/models/swordman.glb（顺带出一张预览图）
  2) Godot 跑一次编辑器导入，刷新 .godot/ 里的资源缓存

用法：
  python tools/rebuild_models.py            重新生成模型
  python tools/rebuild_models.py --pose      顺便出一张姿势检查图
Windows 上也可以直接双击 tools/rebuild_models.bat。

Blender / Godot 装在别处的话，设环境变量 BLENDER_EXE / GODOT_EXE 即可。
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (build_swordman.py 的 --variant, 输出文件名)
MODELS = [("swordman", "swordman"), ("shieldman", "shieldman")]

BLENDER_CANDIDATES = [
    os.environ.get("BLENDER_EXE", ""),
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "blender",
]
GODOT_CANDIDATES = [
    os.environ.get("GODOT_EXE", ""),
    r"C:\Godot4.7\Godot_v4.7-stable_win64_console.exe",
    r"C:\Godot4.7\Godot_v4.7-stable_win64.exe",
    "godot",
]


def find(cands, what, env_name):
    for c in cands:
        if not c:
            continue
        if os.path.isfile(c):
            return c
        if os.sep not in c:            # 在 PATH 里找
            from shutil import which
            p = which(c)
            if p:
                return p
    print("[错误] 找不到 %s。" % what)
    print("       装在别处的话，设环境变量 %s 指向可执行文件，或改本脚本顶部的候选路径。" % env_name)
    print("       试过：")
    for c in cands:
        if c:
            print("         %s" % c)
    sys.exit(1)


def run(cmd, desc):
    print("\n%s" % desc)
    print("  > %s" % " ".join('"%s"' % a if " " in a else a for a in cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print("[错误] 这一步失败了（退出码 %d），上面有报错信息。" % r.returncode)
        sys.exit(r.returncode)


def main():
    pose = "--pose" in sys.argv
    blender = find(BLENDER_CANDIDATES, "Blender", "BLENDER_EXE")
    godot = find(GODOT_CANDIDATES, "Godot", "GODOT_EXE")

    for i, (variant, name) in enumerate(MODELS):
        run([blender, "--background", "--python", os.path.join("tools", "blender", "build_swordman.py"),
             "--", "--variant", variant,
             "--out", os.path.join("assets", "models", name + ".glb"),
             "--render", os.path.join("renders", name + ".png")],
            "[%d/%d] Blender 导出 %s ..." % (i + 1, len(MODELS) + 1, name))

    # 这步不能省：非编辑器模式不会重新导入 glb，游戏里会一直用旧模型
    run([godot, "--headless", "--editor", "--quit", "--path", "."],
        "[%d/%d] Godot 重新导入资源 ..." % (len(MODELS) + 1, len(MODELS) + 1))

    print("\n完成：")
    for _, name in MODELS:
        print("  模型 assets/models/%s.glb   预览图 renders/%s.png" % (name, name))

    if pose:
        shot = os.path.join(ROOT, "renders", "poses.png")
        run([godot, "--path", ".", "res://tests/pose.tscn", "--", "--shot", shot],
            "[额外] 出一张姿势检查图 ...")
        print("  姿势图 renders/poses.png")


if __name__ == "__main__":
    main()
