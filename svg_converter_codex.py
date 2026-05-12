import subprocess
import os
import re
from pathlib import Path
import xml.etree.ElementTree as ET

# ============================================================
#   SVG 批量转换工具（合并版）
#   支持：SVG → PDF、SVG → PNG
# ============================================================

INKSCAPE_PATH = r'D:\software\inkscape\bin\inkscape.com'

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _check_inkscape():
    """检查 Inkscape 是否存在"""
    if not os.path.exists(INKSCAPE_PATH):
        print("Error: 未找到 Inkscape，请检查安装路径。")
        return False
    return True


def _get_svg_files(svg_folder):
    """获取 SVG 文件列表"""
    return [
        file for file in os.listdir(svg_folder)
        if file.lower().endswith(".svg")
    ]


def _parse_style(style):
    """把 SVG style 字符串解析成字典。"""
    result = {}
    if not style:
        return result

    for item in style.split(";"):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        result[key.strip().lower()] = value.strip().lower()

    return result


def _style_value(element, name, default=None):
    """读取 SVG 属性，优先使用独立属性，其次使用 style。"""
    if name in element.attrib:
        return element.attrib[name].strip().lower()

    return _parse_style(element.attrib.get("style", "")).get(name, default)


def _is_zero_opacity(value):
    if value is None:
        return False

    try:
        return float(value) <= 0
    except ValueError:
        return value.strip().lower() in {"0%", "none"}


def _is_white_color(value):
    if value is None:
        return False

    value = value.strip().lower()
    return value in {
        "white",
        "#fff",
        "#ffffff",
        "rgb(255,255,255)",
        "rgb(255, 255, 255)",
    }


def _is_transparent_fill(element):
    fill = _style_value(element, "fill", "black")
    fill_opacity = _style_value(element, "fill-opacity")
    opacity = _style_value(element, "opacity")

    return (
        fill in {"none", "transparent"}
        or _is_zero_opacity(fill_opacity)
        or _is_zero_opacity(opacity)
    )


def _has_visible_stroke(element):
    stroke = _style_value(element, "stroke", "none")
    stroke_opacity = _style_value(element, "stroke-opacity")
    opacity = _style_value(element, "opacity")

    return (
        stroke not in {None, "", "none", "transparent"}
        and not _is_zero_opacity(stroke_opacity)
        and not _is_zero_opacity(opacity)
    )


def _is_white_or_transparent_fill(element):
    fill = _style_value(element, "fill", "black")
    return _is_white_color(fill) or _is_transparent_fill(element)


def _is_rect_element(element):
    tag = element.tag.split("}", 1)[-1]
    return tag == "rect"


def _is_rectangle_path(element):
    """识别 Matplotlib 常见的矩形 path，例如 M x,y H x V y H x Z。"""
    if element.tag.split("}", 1)[-1] != "path":
        return False

    d = element.attrib.get("d", "").strip()
    if not d:
        return False

    normalized = re.sub(r"[, ]+", " ", d.lower()).strip()
    pattern = (
        r"^m\s+[-+0-9.e]+\s+[-+0-9.e]+\s+"
        r"h\s+[-+0-9.e]+\s+"
        r"v\s+[-+0-9.e]+\s+"
        r"h\s+[-+0-9.e]+\s*"
        r"z?$"
    )
    if re.match(pattern, normalized):
        return True

    pattern = (
        r"^m\s+[-+0-9.e]+\s+[-+0-9.e]+\s+"
        r"l\s+[-+0-9.e]+\s+[-+0-9.e]+\s+"
        r"l\s+[-+0-9.e]+\s+[-+0-9.e]+\s+"
        r"l\s+[-+0-9.e]+\s+[-+0-9.e]+\s*"
        r"z?$"
    )
    return bool(re.match(pattern, normalized))


def _is_background_rectangle(element):
    """判断一个 SVG 元素是否是可删除的白色/透明背景矩形。"""
    is_rectangle_shape = _is_rect_element(element) or _is_rectangle_path(element)
    if not is_rectangle_shape:
        return False

    return (
        _is_white_or_transparent_fill(element)
        and not _has_visible_stroke(element)
    )


def remove_svg_background_rectangles(input_svg, output_svg=None):
    """
    删除 SVG 中纯白或透明、且没有可见描边的背景矩形/矩形路径。

    会生成新的 SVG，不修改原始 SVG。
    """
    input_svg = Path(input_svg)
    if output_svg is None:
        output_svg = input_svg.with_name(input_svg.stem + "_clean.svg")
    else:
        output_svg = Path(output_svg)

    tree = ET.parse(input_svg)
    root = tree.getroot()
    parent_map = {child: parent for parent in root.iter() for child in parent}
    removed_count = 0

    for element in list(root.iter()):
        if element is root:
            continue

        if not _is_background_rectangle(element):
            continue

        parent = parent_map.get(element)
        if parent is None:
            continue

        parent.remove(element)
        removed_count += 1

    output_svg.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_svg, encoding="utf-8", xml_declaration=True)
    return str(output_svg), removed_count


def _run_inkscape_export(
    input_svg,
    output_file,
    export_type,
    dpi=None,
    crop_white_edges=True,
):
    """调用 Inkscape 导出文件。"""
    cmd = [
        INKSCAPE_PATH,
        input_svg,
        "--export-type=" + export_type,
        "--export-filename=" + output_file,
    ]

    if dpi is not None:
        cmd.append("--export-dpi=" + str(dpi))

    if crop_white_edges:
        cmd.append("--export-area-drawing")

    subprocess.run(cmd, check=True)


def svg_to_pdf(
    svg_folder="./",
    output_folder="./",
    crop_white_edges=True,
    clean_svg_folder="./SVG_clean",
):
    """
    将指定文件夹中的所有 SVG 文件批量转换为 PDF。

    参数:
        svg_folder (str):             SVG 文件所在的文件夹路径，默认为当前目录。
        output_folder (str):          PDF 输出文件夹路径，默认为当前目录。
        crop_white_edges (bool):      是否使用 Inkscape 裁剪页面白边。
        clean_svg_folder (str):       清理背景后的 SVG 输出文件夹。
    """
    if not _check_inkscape():
        return

    os.makedirs(svg_folder, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(clean_svg_folder, exist_ok=True)

    svg_files = _get_svg_files(svg_folder)

    if not svg_files:
        print("未找到任何 SVG 文件。")
        return

    print(f"找到 {len(svg_files)} 个 SVG 文件，开始导出为 PDF...")
    print(f"输出目录: {os.path.abspath(output_folder)}")
    print("-" * 50)

    for file in svg_files:
        input_svg = os.path.join(svg_folder, file)
        clean_svg = os.path.join(clean_svg_folder, Path(file).stem + "_clean.svg")
        output_pdf = os.path.join(output_folder, Path(file).stem + ".pdf")

        clean_svg, removed_count = remove_svg_background_rectangles(input_svg, clean_svg)
        print(
            f"正在处理: {file} -> {os.path.basename(output_pdf)} "
            f"(已删除背景矩形 {removed_count} 个)"
        )
        _run_inkscape_export(
            input_svg=clean_svg,
            output_file=output_pdf,
            export_type="pdf",
            crop_white_edges=crop_white_edges,
        )

    print("-" * 50)
    print("全部 PDF 转换完成！")


def svg_to_png(
    svg_folder="./",
    output_folder="./PNG",
    dpi=300,
    crop_white_edges=True,
    clean_svg_folder="./SVG_clean",
):
    """
    将指定文件夹中的所有 SVG 文件批量转换为 PNG。

    参数:
        svg_folder (str):             SVG 文件所在的文件夹路径，默认为当前目录。
        output_folder (str):          PNG 输出文件夹路径，默认为 ./PNG。
        dpi (int):                    输出 PNG 的分辨率（150=网页, 300=打印, 600=高清）。
        crop_white_edges (bool):      是否使用 Inkscape 裁剪页面白边。
        clean_svg_folder (str):       清理背景后的 SVG 输出文件夹。
    """
    if not _check_inkscape():
        return

    # 如果目录不存在则自动创建
    os.makedirs(svg_folder, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(clean_svg_folder, exist_ok=True)

    svg_files = _get_svg_files(svg_folder)

    if not svg_files:
        print("未找到任何 SVG 文件。")
        return

    print(f"找到 {len(svg_files)} 个 SVG 文件，导出 DPI: {dpi}")
    print(f"输出目录: {os.path.abspath(output_folder)}")
    print("-" * 50)

    for file in svg_files:
        input_svg = os.path.join(svg_folder, file)
        clean_svg = os.path.join(clean_svg_folder, Path(file).stem + "_clean.svg")
        output_png = os.path.join(output_folder, Path(file).stem + ".png")

        clean_svg, removed_count = remove_svg_background_rectangles(input_svg, clean_svg)
        print(
            f"正在处理: {file} -> {os.path.basename(output_png)} "
            f"(已删除背景矩形 {removed_count} 个)"
        )
        _run_inkscape_export(
            input_svg=clean_svg,
            output_file=output_png,
            export_type="png",
            dpi=dpi,
            crop_white_edges=crop_white_edges,
        )

    print("-" * 50)
    print("全部 PNG 转换完成！")


# ============================================================
#   主程序入口 —— 在这里选择转换模式并设置参数
# ============================================================
if __name__ == "__main__":

    # ----- 通用参数 -----
    svg_folder = "./SVG"          # SVG 文件所在的文件夹路径
    output_folder = "./PDF"       # 输出文件夹路径
    clean_svg_folder = "./SVG_clean"  # 清理背景后的 SVG 输出文件夹


    # ===== 选择转换模式（注释掉不需要的那行）=====
    svg_to_pdf(svg_folder, output_folder, clean_svg_folder=clean_svg_folder)
    # svg_to_png(svg_folder, output_folder, dpi=600, clean_svg_folder=clean_svg_folder)
