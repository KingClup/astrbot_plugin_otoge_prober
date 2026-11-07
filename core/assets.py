"""素材管理（WebUI「素材」板块）：舞萌 / 中二的图标、版本 logo、B50 背景、音符、曲绘。

命名规则（平铺命名，一次可以多选上传，也可以打成 zip）：
    <游戏>_<类型>_<名字>.png        游戏 = mai / chu，大小写不敏感，jpg / webp 也行，统一转成 PNG 保存

    mai_rank_sssp.png        评级（sssp sss ssp ss sp s aaa aa a bbb bb b c d）
    mai_fc_ap.png            FC / AP 图标（fc fcp ap app）
    mai_fs_fsdp.png          SYNC / FS 图标（sync fs fsp fsd fsdp）
    mai_type_dx.png          でらっくす / スタンダード 徽章（dx std）
    mai_dxstar_3.png         DX 星（1 2 3）
    mai_rating_07.png        DX RATING 底板（01–12，按分段）
    mai_note_tap.png         Note 表头图标（tap hold slide touch break）
    mai_logo_circle_plus.png 小版本 logo（版本名小写，空格换成 _：maimai_plus、deluxe、buddies_plus、magical…）
    mai_bg_circle_plus.png   B50 / 卡片背景（default = 所有版本通用）
    mai_head_circle_plus.png B50 页头大 logo（default = 所有版本通用）
    mai_jacket_11475.png     本机曲绘（写曲目 ID，DX 的 1xxxx 也行）
    mai_deco_xxx.png         背景装饰贴纸（名字随意）
    chu_logo_sun.png         中二版本 logo（chunithm chunithm_plus air air_plus … new new_plus sun sun_plus
                             luminous luminous_plus verse xverse xversex）
    chu_bg_default.png       中二 B50 背景（default 或版本名，如 chu_bg_xversex）
    chu_head_default.png     中二 B50 页头 logo
    chu_digits.png           中二 B50 rating 数字贴图

zip 包里可以是上面这样平铺命名的文件，也可以是插件数据目录的结构：
    mai/themes/icons/rank_sssp.png、chu/version_logos/sun.png、themes/…（旧的舞萌素材包）、version_logos/…
"""
from __future__ import annotations

import base64
import io
import os
import re
import zipfile
from dataclasses import dataclass

from PIL import Image

MAX_FILE = 8 * 1024 * 1024
MAX_PACK = 200 * 1024 * 1024
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")

RANKS = ("sssp", "sss", "ssp", "ss", "sp", "s", "aaa", "aa", "a", "bbb", "bb", "b", "c", "d")
RANK_LABEL = {"sssp": "SSS+", "sss": "SSS", "ssp": "SS+", "ss": "SS", "sp": "S+", "s": "S", "aaa": "AAA",
              "aa": "AA", "a": "A", "bbb": "BBB", "bb": "BB", "b": "B", "c": "C", "d": "D"}
FC = {"fc": "FC", "fcp": "FC+", "ap": "AP", "app": "AP+"}
FS = {"sync": "SYNC", "fs": "FS", "fsp": "FS+", "fsd": "FDX", "fsdp": "FDX+"}
NOTES = {"tap": "TAP", "hold": "HOLD", "slide": "SLIDE", "touch": "TOUCH", "break": "BREAK"}
CHU_VERSIONS = ("CHUNITHM", "CHUNITHM PLUS", "AIR", "AIR PLUS", "STAR", "STAR PLUS", "AMAZON", "AMAZON PLUS",
                "CRYSTAL", "CRYSTAL PLUS", "PARADISE", "PARADISE LOST", "NEW!!", "NEW PLUS!!", "SUN", "SUN PLUS",
                "LUMINOUS", "LUMINOUS PLUS", "VERSE", "X-VERSE", "X-VERSE-X")


def mai_slug(version: str) -> str:
    return version.lower().replace("maimaiでらっくす", "deluxe").replace(" ", "_")


def chu_slug(version: str) -> str:
    try:
        from ..chuni.logos import slug
    except ImportError:  # tests
        from chuni.logos import slug
    return slug(version)


def chu_theme_dir(version: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", version or "default").strip("_") or "default"


@dataclass
class Slot:
    key: str          # flat file name without extension, e.g. mai_rank_sssp
    game: str         # mai / chu
    rel: str          # path under the game's data folder, e.g. themes/icons/rank_sssp.png
    label: str        # what the user sees
    group: str


class AssetManager:
    def __init__(self, data_root: str, mai_versions=(), chu_current: str | None = None):
        self.root = os.path.realpath(data_root)            # plugin_data/astrbot_plugin_otoge_prober
        self.mai_versions = list(mai_versions)
        self.chu_current = chu_current

    # ---------- the catalogue of slots ----------
    def groups(self, mai_current: list[str] | None = None) -> list[dict]:
        g: list[tuple[str, str, list[Slot]]] = []

        def mai(group, items):
            g.append(("mai", group, [Slot(k, "mai", rel, lab, group) for k, rel, lab in items]))

        def chu(group, items):
            g.append(("chu", group, [Slot(k, "chu", rel, lab, group) for k, rel, lab in items]))

        mai("评级", [(f"mai_rank_{r}", f"themes/icons/rank_{r}.png", RANK_LABEL[r]) for r in RANKS])
        mai("FC / AP · SYNC / FS", [(f"mai_fc_{k}", f"themes/icons/fc_{k}.png", v) for k, v in FC.items()]
            + [(f"mai_fs_{k}", f"themes/icons/fs_{k}.png", v) for k, v in FS.items()])
        mai("谱面类型 · DX 星", [("mai_type_dx", "themes/icons/type_dx.png", "でらっくす"),
                              ("mai_type_std", "themes/icons/type_std.png", "スタンダード")]
            + [(f"mai_dxstar_{i}", f"themes/icons/dxstar_{i}.png", f"DX 星 {i}") for i in (1, 2, 3)])
        mai("DX RATING 底板", [(f"mai_rating_{i:02d}", f"themes/icons/rating_{i:02d}.png", f"{i:02d}")
                             for i in range(1, 13)])
        mai("Note 图标", [(f"mai_note_{k}", f"themes/icons/note_{k}.png", v) for k, v in NOTES.items()])
        mai("版本 logo（小）", [(f"mai_logo_{mai_slug(v)}", f"themes/logos/{mai_slug(v)}.png", v)
                            for v in self.mai_versions])
        heads = ["default", *(mai_current or [])]
        mai("B50 背景 · 页头 logo", [(f"mai_bg_{mai_slug(v)}", f"themes/{v}/bg.png", f"背景 · {v}") for v in heads]
            + [(f"mai_head_{mai_slug(v)}", f"themes/{v}/logo.png", f"页头 · {v}") for v in heads])
        chu("版本 logo", [(f"chu_logo_{chu_slug(v)}", f"version_logos/{chu_slug(v)}.png", v) for v in CHU_VERSIONS])
        cheads = ["default"] + ([self.chu_current] if self.chu_current else [])
        chu("B50 背景 · 页头 logo · 数字", [(f"chu_bg_{chu_slug(v) if v != 'default' else 'default'}",
                                         f"themes/{chu_theme_dir(None if v == 'default' else v)}/bg.png", f"背景 · {v}")
                                        for v in cheads]
            + [(f"chu_head_{chu_slug(v) if v != 'default' else 'default'}",
                f"themes/{chu_theme_dir(None if v == 'default' else v)}/logo.png", f"页头 · {v}") for v in cheads]
            + [("chu_digits", "themes/digits.png", "rating 数字")])
        out = []
        for game, group, slots in g:
            items = []
            for s in slots:
                p = self._path(game, s.rel)
                items.append({"key": s.key, "rel": f"{game}/{s.rel}", "label": s.label,
                              "exists": os.path.isfile(p), "size": os.path.getsize(p) if os.path.isfile(p) else 0})
            out.append({"game": game, "group": group, "items": items,
                        "have": sum(i["exists"] for i in items), "total": len(items)})
        return out

    # ---------- name → place ----------
    def resolve(self, filename: str) -> tuple[str, str] | None:
        """Flat file name → (game, rel path) or None."""
        stem, ext = os.path.splitext(os.path.basename(filename or ""))
        if ext.lower() not in IMAGE_EXT:
            return None
        k = stem.strip().lower().replace("-", "_").replace(" ", "_")
        m = re.fullmatch(r"(mai|chu)_(.+)", k)
        if not m:
            return None
        game, rest = m.groups()
        if game == "mai":
            if (mm := re.fullmatch(r"rank_(" + "|".join(RANKS) + ")", rest)):
                return game, f"themes/icons/rank_{mm.group(1)}.png"
            if (mm := re.fullmatch(r"(fc_(?:fc|fcp|ap|app)|fs_(?:sync|fs|fsp|fsd|fsdp)|type_(?:dx|std)|dxstar_[123]|"
                                   r"note_(?:tap|hold|slide|touch|break))", rest)):
                return game, f"themes/icons/{mm.group(1)}.png"
            if (mm := re.fullmatch(r"rating_(\d{1,2})", rest)) and 1 <= int(mm.group(1)) <= 12:
                return game, f"themes/icons/rating_{int(mm.group(1)):02d}.png"
            if (mm := re.fullmatch(r"logo_(.+)", rest)) and (v := self._mai_version(mm.group(1))):
                return game, f"themes/logos/{mai_slug(v)}.png"
            if (mm := re.fullmatch(r"(bg|head)_(.+)", rest)):
                v = "default" if mm.group(2) == "default" else self._mai_version(mm.group(2))
                if v:
                    return game, f"themes/{v}/{'bg' if mm.group(1) == 'bg' else 'logo'}.png"
            if (mm := re.fullmatch(r"jacket_(\d{1,6})", rest)):
                return game, f"jackets_hdd/{int(mm.group(1)) % 10000:06d}.png"
            if (mm := re.fullmatch(r"deco_([a-z0-9_]{1,40})", rest)):
                return game, f"themes/deco/{mm.group(1)}.png"
            return None
        if (mm := re.fullmatch(r"logo_(.+)", rest)) and (v := self._chu_version(mm.group(1))):
            return game, f"version_logos/{chu_slug(v)}.png"
        if (mm := re.fullmatch(r"(bg|head)_(.+)", rest)):
            v = None if mm.group(2) == "default" else self._chu_version(mm.group(2))
            if v or mm.group(2) == "default":
                return game, f"themes/{chu_theme_dir(v)}/{'bg' if mm.group(1) == 'bg' else 'logo'}.png"
        if rest == "digits":
            return game, "themes/digits.png"
        return None

    def _mai_version(self, s: str) -> str | None:
        return next((v for v in self.mai_versions if mai_slug(v) == s), None)

    @staticmethod
    def _chu_version(s: str) -> str | None:
        return next((v for v in CHU_VERSIONS if chu_slug(v) == s), None)

    def _path(self, game: str, rel: str) -> str:
        p = os.path.realpath(os.path.join(self.root, game, rel))
        if not p.startswith(os.path.join(self.root, game) + os.sep):
            raise ValueError("路径不合法")
        return p

    # ---------- save / delete / preview ----------
    def save(self, game: str, rel: str, data: bytes) -> dict:
        if len(data) > MAX_FILE:
            raise ValueError("文件太大（上限 8 MB）")
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception:  # noqa: BLE001
            raise ValueError("不是能识别的图片（支持 PNG / JPG / WEBP）") from None
        dest = self._path(game, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
        tmp = dest + ".tmp"
        im.save(tmp, "PNG")
        os.replace(tmp, dest)
        return {"saved": f"{game}/{rel}", "size": list(im.size)}

    def upload(self, filename: str, data: bytes, key: str = "") -> dict:
        """key = a slot key (single upload from the grid) or "" / "auto" (route by file name)."""
        if key and key != "auto":
            target = self.resolve(key + ".png")
            if target is None:
                raise ValueError(f"未知的素材位：{key}")
            return self.save(*target, data)
        if (filename or "").lower().endswith(".zip") or data[:2] == b"PK":
            return self.import_zip(data)
        target = self.resolve(filename)
        if target is None:
            raise ValueError(f"「{filename}」不符合命名规则，不知道放哪（例：mai_rank_sssp.png、chu_logo_sun.png）")
        return self.save(*target, data)

    def import_zip(self, data: bytes) -> dict:
        if len(data) > MAX_PACK:
            raise ValueError("素材包太大（上限 200 MB）")
        saved, skipped = [], []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                base = name.rsplit("/", 1)[-1]
                if base.startswith(".") or "__MACOSX" in name:
                    continue
                target = self.resolve(base) or self._layout(name)
                if target is None:
                    skipped.append(name)
                    continue
                try:
                    with z.open(info) as f:
                        saved.append(self.save(*target, f.read())["saved"])
                except ValueError as e:
                    skipped.append(f"{name}（{e}）")
        return {"saved": f"素材包：放好 {len(saved)} 个文件" + (f"，跳过 {len(skipped)} 个" if skipped else ""),
                "files": saved, "skipped": skipped[:50], "size": [len(saved), len(skipped)]}

    @staticmethod
    def _layout(path: str) -> tuple[str, str] | None:
        """Folder-structured packs: mai/…, chu/…, themes/… (old maimai pack), version_logos/… (chuni logos)."""
        if not path.lower().endswith(IMAGE_EXT):
            return None
        p = path.lstrip("/")
        for prefix, game, keep in (("mai/", "mai", ""), ("chu/", "chu", ""), ("themes/", "mai", "themes/"),
                                   ("version_logos/", "chu", "version_logos/"), ("jackets_hdd/", "mai", "jackets_hdd/")):
            if p.startswith(prefix):
                rel = keep + p[len(prefix):]
                if ".." in rel.split("/"):
                    return None
                return game, os.path.splitext(rel)[0] + ".png"
        return None

    def delete(self, rel: str) -> dict:
        game, _, sub = (rel or "").partition("/")
        if game not in ("mai", "chu") or not sub:
            raise ValueError("路径不合法")
        p = self._path(game, sub)
        if not os.path.isfile(p):
            raise ValueError("文件不存在")
        os.remove(p)
        return {"deleted": rel}

    def thumb(self, rel: str, max_side: int = 320) -> dict:
        game, _, sub = (rel or "").partition("/")
        p = self._path(game, sub)
        if not os.path.isfile(p):
            raise ValueError("文件不存在")
        with Image.open(p) as im:
            w, h = im.size
            im = im.convert("RGBA")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "PNG")
        return {"image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), "size": [w, h],
                "rel": rel}


RULES = [
    ("舞萌 · 图标", "mai_rank_<评级>  mai_fc_<fc|fcp|ap|app>  mai_fs_<sync|fs|fsp|fsd|fsdp>  mai_type_<dx|std>  "
                 "mai_dxstar_<1-3>  mai_rating_<01-12>  mai_note_<tap|hold|slide|touch|break>",
     "mai_rank_sssp.png、mai_fc_app.png、mai_rating_07.png"),
    ("舞萌 · 版本 logo", "mai_logo_<版本>，版本名小写、空格换成 _（maimai でらっくす 写 deluxe）",
     "mai_logo_circle_plus.png、mai_logo_deluxe_plus.png"),
    ("舞萌 · B50 背景 / 页头 logo", "mai_bg_<版本|default>  mai_head_<版本|default>（default = 所有版本通用）",
     "mai_bg_default.png、mai_head_prism_plus.png"),
    ("舞萌 · 曲绘 / 装饰", "mai_jacket_<曲目ID>（DX 的 1xxxx 也行）  mai_deco_<随便起名>",
     "mai_jacket_1475.png、mai_deco_star.png"),
    ("中二 · 版本 logo", "chu_logo_<版本>：chunithm chunithm_plus air air_plus star … new new_plus sun sun_plus "
                       "luminous luminous_plus verse xverse xversex", "chu_logo_sun.png、chu_logo_xversex.png"),
    ("中二 · B50", "chu_bg_<版本|default>  chu_head_<版本|default>  chu_digits", "chu_bg_default.png、chu_digits.png"),
]
TIPS = [
    "文件名大小写、- 和 _ 都不讲究；PNG / JPG / WEBP 都行，保存时统一转成 PNG（透明背景会保留）。",
    "按规则命名后可以一次多选很多张上传，或者打成一个 zip 上传；zip 里也可以按插件数据目录的结构放（mai/themes/icons/…、chu/version_logos/…）。",
    "单张不超过 8 MB，zip 不超过 200 MB。图标建议用透明背景；版本 logo 建议高度 100–300 像素。",
    "游戏素材的版权属于 SEGA：只在自己的机器上用，不要随插件分发。",
]
