import subprocess
import os
import re
import sys
import argparse
import tempfile
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


def _get_svg_paths(svg_input):
    """获取 SVG 路径列表；svg_input 可以是单个文件或文件夹。"""
    svg_input = Path(svg_input)

    if svg_input.is_file():
        if svg_input.suffix.lower() != ".svg":
            raise ValueError(f"输入文件不是 SVG: {svg_input}")
        return [svg_input]

    if not svg_input.exists():
        if svg_input.suffix.lower() == ".svg":
            raise FileNotFoundError(f"未找到 SVG 文件: {svg_input}")
        svg_input.mkdir(parents=True, exist_ok=True)

    return sorted(
        file for file in svg_input.iterdir()
        if file.is_file() and file.suffix.lower() == ".svg"
    )


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


def _is_rgba_zero_alpha(value):
    if value is None:
        return False

    match = re.fullmatch(
        r"rgba\(\s*[^,]+\s*,\s*[^,]+\s*,\s*[^,]+\s*,\s*([^)]+)\s*\)",
        value.strip().lower(),
    )
    if not match:
        return False

    alpha = match.group(1).strip()
    return _is_zero_opacity(alpha)


def _is_white_color(value):
    if value is None:
        return False

    value = value.strip().lower().replace(" ", "")
    return value in {
        "white",
        "#fff",
        "#ffffff",
        "rgb(255,255,255)",
    }


def _is_transparent_fill(element):
    fill = _style_value(element, "fill", "black")
    fill_opacity = _style_value(element, "fill-opacity")
    opacity = _style_value(element, "opacity")

    return (
        fill in {"none", "transparent"}
        or _is_rgba_zero_alpha(fill)
        or _is_zero_opacity(fill_opacity)
        or _is_zero_opacity(opacity)
    )


def _is_white_fill(element):
    fill = _style_value(element, "fill", "black")
    fill_opacity = _style_value(element, "fill-opacity")
    opacity = _style_value(element, "opacity")

    return (
        _is_white_color(fill)
        and not _is_zero_opacity(fill_opacity)
        and not _is_zero_opacity(opacity)
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


def _is_rect_element(element):
    tag = element.tag.split("}", 1)[-1]
    return tag == "rect"


def _tag_name(element):
    return element.tag.split("}", 1)[-1]


def _element_id(element):
    return element.attrib.get("id", "")


def _is_matplotlib_svg(root):
    for element in root.iter():
        if element.text and "matplotlib" in element.text.lower():
            return True
    return False


def _parse_float(value, default=0.0):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_svg_length(value):
    """解析 SVG 长度，按 SVG 用户单位返回；pt/px 等单位只取数值。"""
    if value is None:
        return None

    match = re.match(r"\s*([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)", value)
    if not match:
        return None

    return float(match.group(1))


def _svg_viewport(root):
    view_box = root.attrib.get("viewBox")
    if view_box:
        values = re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", view_box)
        if len(values) == 4:
            x, y, width, height = map(float, values)
            if width > 0 and height > 0:
                return x, y, width, height

    width = _parse_svg_length(root.attrib.get("width"))
    height = _parse_svg_length(root.attrib.get("height"))
    if width and height:
        return 0.0, 0.0, width, height

    return None


def _rect_bbox(element):
    if not _is_rect_element(element):
        return None

    x = _parse_float(element.attrib.get("x"), 0.0)
    y = _parse_float(element.attrib.get("y"), 0.0)
    width = _parse_float(element.attrib.get("width"), 0.0)
    height = _parse_float(element.attrib.get("height"), 0.0)

    if width <= 0 or height <= 0:
        return None

    return x, y, x + width, y + height


def _path_tokens(path_d):
    return re.findall(
        r"[MmLlHhVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?",
        path_d,
    )


def _rectangle_path_points(element):
    """解析只由 M/L/H/V/Z 组成的单个矩形 path，返回角点列表。"""
    if element.tag.split("}", 1)[-1] != "path":
        return None

    d = element.attrib.get("d", "").strip()
    if not d:
        return None

    tokens = _path_tokens(d)
    if not tokens:
        return None

    points = []
    index = 0
    command = None
    current = (0.0, 0.0)
    start = None
    closed = False

    def is_command(token):
        return len(token) == 1 and token.isalpha()

    def read_number():
        nonlocal index
        if index >= len(tokens) or is_command(tokens[index]):
            return None
        value = float(tokens[index])
        index += 1
        return value

    while index < len(tokens):
        if is_command(tokens[index]):
            command = tokens[index]
            index += 1

        if command is None:
            return None

        lower_command = command.lower()
        relative = command.islower()

        if lower_command == "z":
            closed = True
            if start is not None:
                current = start
            command = None
            continue

        if lower_command == "m":
            x = read_number()
            y = read_number()
            if x is None or y is None:
                return None
            if relative:
                x += current[0]
                y += current[1]
            current = (x, y)
            start = current
            points.append(current)
            command = "l" if relative else "L"
            continue

        if lower_command == "l":
            x = read_number()
            y = read_number()
            if x is None or y is None:
                return None
            if relative:
                x += current[0]
                y += current[1]
            current = (x, y)
            points.append(current)
            continue

        if lower_command == "h":
            x = read_number()
            if x is None:
                return None
            if relative:
                x += current[0]
            current = (x, current[1])
            points.append(current)
            continue

        if lower_command == "v":
            y = read_number()
            if y is None:
                return None
            if relative:
                y += current[1]
            current = (current[0], y)
            points.append(current)
            continue

        return None

    if closed and points and points[-1] == points[0]:
        points = points[:-1]

    unique_points = []
    for point in points:
        if point not in unique_points:
            unique_points.append(point)

    if len(unique_points) != 4:
        return None

    xs = {round(point[0], 6) for point in unique_points}
    ys = {round(point[1], 6) for point in unique_points}
    if len(xs) != 2 or len(ys) != 2:
        return None

    return unique_points


def _rectangle_path_bbox(element):
    points = _rectangle_path_points(element)
    if points is None:
        return None

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _rectangle_bbox(element):
    return _rect_bbox(element) or _rectangle_path_bbox(element)


def _matrix_multiply(left, right):
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(transform):
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not transform:
        return matrix

    for name, args in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", transform):
        values = [
            float(value) for value in
            re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", args)
        ]
        name = name.lower()

        if name == "matrix" and len(values) == 6:
            next_matrix = tuple(values)
        elif name == "translate" and values:
            tx = values[0]
            ty = values[1] if len(values) > 1 else 0.0
            next_matrix = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale" and values:
            sx = values[0]
            sy = values[1] if len(values) > 1 else sx
            next_matrix = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        else:
            return None

        matrix = _matrix_multiply(matrix, next_matrix)

    return matrix


def _element_transform(element, parent_map):
    transforms = []
    current = element
    while current is not None:
        transform = current.attrib.get("transform")
        if transform:
            transforms.append(transform)
        current = parent_map.get(current)

    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for transform in reversed(transforms):
        next_matrix = _parse_transform(transform)
        if next_matrix is None:
            return None
        matrix = _matrix_multiply(matrix, next_matrix)

    return matrix


def _apply_transform_to_bbox(bbox, matrix):
    x1, y1, x2, y2 = bbox
    a, b, c, d, e, f = matrix
    points = [
        (x1, y1),
        (x1, y2),
        (x2, y1),
        (x2, y2),
    ]
    transformed = [
        (a * x + c * y + e, b * x + d * y + f)
        for x, y in points
    ]
    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    return min(xs), min(ys), max(xs), max(ys)


def _is_in_non_rendering_context(element, parent_map):
    non_rendering_tags = {
        "defs",
        "clipPath",
        "mask",
        "marker",
        "pattern",
        "symbol",
    }
    current = parent_map.get(element)
    while current is not None:
        if _tag_name(current) in non_rendering_tags:
            return True
        current = parent_map.get(current)

    return False


def _is_canvas_sized_bbox(bbox, viewport, min_area_ratio=0.90):
    vx, vy, vwidth, vheight = viewport
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    if width <= 0 or height <= 0:
        return False

    area_ratio = (width * height) / (vwidth * vheight)
    if area_ratio < min_area_ratio:
        return False

    tolerance_x = max(2.0, vwidth * 0.03)
    tolerance_y = max(2.0, vheight * 0.03)

    return (
        x1 <= vx + tolerance_x
        and y1 <= vy + tolerance_y
        and x2 >= vx + vwidth - tolerance_x
        and y2 >= vy + vheight - tolerance_y
    )


def _is_matplotlib_background_patch(element, root, parent_map, is_matplotlib):
    if not is_matplotlib:
        return False

    if _is_in_non_rendering_context(element, parent_map):
        return False

    if not _is_white_fill(element):
        return False

    if _has_visible_stroke(element):
        return False

    bbox = _rectangle_bbox(element)
    if bbox is None:
        return False

    parent = parent_map.get(element)
    grandparent = parent_map.get(parent) if parent is not None else None
    parent_id = _element_id(parent) if parent is not None else ""
    grandparent_id = _element_id(grandparent) if grandparent is not None else ""

    # Matplotlib puts figure/axes background rectangles in patch_N groups.
    # Do not delete arbitrary white rectangles, legends, labels, or 3D panes.
    if not re.fullmatch(r"patch_[12]", parent_id):
        return False

    if grandparent_id not in {"figure_1", "axes_1"}:
        return False

    matrix = _element_transform(element, parent_map)
    if matrix is None:
        return False

    viewport = _svg_viewport(root)
    if viewport is None:
        return False

    transformed_bbox = _apply_transform_to_bbox(bbox, matrix)
    vx, vy, vwidth, vheight = viewport
    x1, y1, x2, y2 = transformed_bbox
    width = x2 - x1
    height = y2 - y1
    if width <= 0 or height <= 0:
        return False

    area_ratio = (width * height) / (vwidth * vheight)
    return area_ratio >= 0.20


def _is_background_rectangle(
    element,
    root,
    parent_map,
    is_matplotlib,
    min_area_ratio=0.90,
):
    """
    判断一个 SVG 元素是否是可删除的透明占位背景矩形。

    只删除透明/不可见且无描边、尺寸接近整张 SVG 画布的矩形。
    白色矩形会保留，避免误删用户主动添加的白底或图内白色元素。
    """
    if _is_matplotlib_background_patch(element, root, parent_map, is_matplotlib):
        return True

    if _is_in_non_rendering_context(element, parent_map):
        return False

    if not _is_transparent_fill(element):
        return False

    if _has_visible_stroke(element):
        return False

    bbox = _rectangle_bbox(element)
    if bbox is None:
        return False

    matrix = _element_transform(element, parent_map)
    if matrix is None:
        return False

    viewport = _svg_viewport(root)
    if viewport is None:
        return False

    transformed_bbox = _apply_transform_to_bbox(bbox, matrix)
    return _is_canvas_sized_bbox(
        transformed_bbox,
        viewport,
        min_area_ratio=min_area_ratio,
    )


def remove_svg_background_rectangles(
    input_svg,
    output_svg=None,
    min_area_ratio=0.90,
):
    """
    删除 SVG 中透明、无描边、接近整张画布的占位背景矩形/矩形路径。

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
    is_matplotlib = _is_matplotlib_svg(root)
    removed_count = 0

    for element in list(root.iter()):
        if element is root:
            continue

        if not _is_background_rectangle(
            element,
            root,
            parent_map,
            is_matplotlib,
            min_area_ratio=min_area_ratio,
        ):
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


def _clean_svg_for_export(
    input_svg,
    clean_svg_folder=None,
    min_background_area_ratio=0.90,
):
    """
    生成供 Inkscape 导出的清理版 SVG。

    clean_svg_folder 为 True 或目录路径时会保留清理后的 SVG；
    为 None/False 时只使用临时文件，导出完成后由调用方删除。
    """
    input_svg = Path(input_svg)

    if clean_svg_folder is True:
        clean_svg_dir = Path("./SVG_clean")
    elif clean_svg_folder:
        clean_svg_dir = Path(clean_svg_folder)
    else:
        clean_svg_dir = None

    if clean_svg_dir is not None:
        clean_svg_dir.mkdir(parents=True, exist_ok=True)
        clean_svg = clean_svg_dir / f"{input_svg.stem}_clean.svg"
        should_delete_clean_svg = False
    else:
        temp_file = tempfile.NamedTemporaryFile(
            prefix=f"{input_svg.stem}_clean_",
            suffix=".svg",
            delete=False,
        )
        temp_file.close()
        clean_svg = Path(temp_file.name)
        should_delete_clean_svg = True

    clean_svg, removed_count = remove_svg_background_rectangles(
        input_svg,
        clean_svg,
        min_area_ratio=min_background_area_ratio,
    )
    return clean_svg, removed_count, should_delete_clean_svg


def svg_to_pdf(
    svg_folder="./",
    output_folder="./",
    crop_white_edges=True,
    clean_svg_folder=None,
    min_background_area_ratio=0.90,
    svg_file=None,
):
    """
    将指定 SVG 文件或文件夹中的所有 SVG 文件转换为 PDF。

    参数:
        svg_folder (str):             SVG 文件或 SVG 文件夹路径，默认为当前目录。
        svg_file (str):               单个 SVG 文件路径；传入后优先于 svg_folder。
        output_folder (str):          PDF 输出文件夹路径，默认为当前目录。
        crop_white_edges (bool):      是否使用 Inkscape 裁剪页面白边。
        clean_svg_folder:             True 时保存到 ./SVG_clean；字符串时保存到指定文件夹；
                                      None/False 时不保留清理后的 SVG。
        min_background_area_ratio:    透明占位框至少占 SVG 画布的比例。
    """
    if not _check_inkscape():
        return

    os.makedirs(output_folder, exist_ok=True)
    svg_paths = _get_svg_paths(svg_file if svg_file is not None else svg_folder)

    if not svg_paths:
        print("未找到任何 SVG 文件。")
        return

    print(f"找到 {len(svg_paths)} 个 SVG 文件，开始导出为 PDF...")
    print(f"输出目录: {os.path.abspath(output_folder)}")
    print("-" * 50)

    for input_svg in svg_paths:
        output_pdf = Path(output_folder) / f"{input_svg.stem}.pdf"

        clean_svg, removed_count, should_delete_clean_svg = _clean_svg_for_export(
            input_svg,
            clean_svg_folder=clean_svg_folder,
            min_background_area_ratio=min_background_area_ratio,
        )
        print(
            f"正在处理: {input_svg.name} -> {output_pdf.name} "
            f"(已删除背景占位框 {removed_count} 个)"
        )
        try:
            _run_inkscape_export(
                input_svg=clean_svg,
                output_file=str(output_pdf),
                export_type="pdf",
                crop_white_edges=crop_white_edges,
            )
        finally:
            if should_delete_clean_svg:
                Path(clean_svg).unlink(missing_ok=True)

    print("-" * 50)
    print("全部 PDF 转换完成！")


def svg_to_png(
    svg_folder="./",
    output_folder="./PNG",
    dpi=600,
    crop_white_edges=True,
    clean_svg_folder=None,
    min_background_area_ratio=0.90,
):
    """
    将指定 SVG 文件或文件夹中的所有 SVG 文件转换为 PNG。

    参数:
        svg_folder (str):             SVG 文件或 SVG 文件夹路径，默认为当前目录。
        output_folder (str):          PNG 输出文件夹路径，默认为 ./PNG。
        dpi (int):                    输出 PNG 的分辨率（150=网页, 300=打印, 600=高清）。
        crop_white_edges (bool):      是否使用 Inkscape 裁剪页面白边。
        clean_svg_folder:             True 时保存到 ./SVG_clean；字符串时保存到指定文件夹；
                                      None/False 时不保留清理后的 SVG。
        min_background_area_ratio:    透明占位框至少占 SVG 画布的比例。
    """
    if not _check_inkscape():
        return

    os.makedirs(output_folder, exist_ok=True)
    svg_paths = _get_svg_paths(svg_folder)

    if not svg_paths:
        print("未找到任何 SVG 文件。")
        return

    print(f"找到 {len(svg_paths)} 个 SVG 文件，导出 DPI: {dpi}")
    print(f"输出目录: {os.path.abspath(output_folder)}")
    print("-" * 50)

    for input_svg in svg_paths:
        output_png = Path(output_folder) / f"{input_svg.stem}.png"

        clean_svg, removed_count, should_delete_clean_svg = _clean_svg_for_export(
            input_svg,
            clean_svg_folder=clean_svg_folder,
            min_background_area_ratio=min_background_area_ratio,
        )
        print(
            f"正在处理: {input_svg.name} -> {output_png.name} "
            f"(已删除背景占位框 {removed_count} 个)"
        )
        try:
            _run_inkscape_export(
                input_svg=clean_svg,
                output_file=str(output_png),
                export_type="png",
                dpi=dpi,
                crop_white_edges=crop_white_edges,
            )
        finally:
            if should_delete_clean_svg:
                Path(clean_svg).unlink(missing_ok=True)

    print("-" * 50)
    print("全部 PNG 转换完成！")


def clean_svg(
    svg_input="./",
    output_folder="./SVG_clean",
    min_background_area_ratio=0.90,
):
    """只清理 SVG，不导出 PDF/PNG；支持单个 SVG 或文件夹。"""
    os.makedirs(output_folder, exist_ok=True)
    svg_paths = _get_svg_paths(svg_input)

    if not svg_paths:
        print("未找到任何 SVG 文件。")
        return

    print(f"找到 {len(svg_paths)} 个 SVG 文件，开始清理背景占位框...")
    for input_svg in svg_paths:
        output_svg = Path(output_folder) / f"{input_svg.stem}_clean.svg"
        _, removed_count = remove_svg_background_rectangles(
            input_svg,
            output_svg,
            min_area_ratio=min_background_area_ratio,
        )
        print(f"已清理: {input_svg.name} (已删除背景占位框 {removed_count} 个)")


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="SVG 清理与导出工具，支持单个 SVG 或文件夹。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pdf_parser = subparsers.add_parser("pdf", help="导出为 PDF")
    pdf_parser.add_argument("svg_input", help="SVG 文件或文件夹")
    pdf_parser.add_argument("-o", "--output-folder", default="./PDF")
    pdf_parser.add_argument(
        "--clean-svg-folder",
        nargs="?",
        const="./SVG_clean",
        default=None,
        help="保留清理后的 SVG；可不填路径，默认保存到 ./SVG_clean",
    )
    pdf_parser.add_argument("--no-crop", action="store_true")
    pdf_parser.add_argument("--min-background-area-ratio", type=float, default=0.90)

    png_parser = subparsers.add_parser("png", help="导出为 PNG")
    png_parser.add_argument("svg_input", help="SVG 文件或文件夹")
    png_parser.add_argument("-o", "--output-folder", default="./PNG")
    png_parser.add_argument(
        "--clean-svg-folder",
        nargs="?",
        const="./SVG_clean",
        default=None,
        help="保留清理后的 SVG；可不填路径，默认保存到 ./SVG_clean",
    )
    png_parser.add_argument("--dpi", type=int, default=600)
    png_parser.add_argument("--no-crop", action="store_true")
    png_parser.add_argument("--min-background-area-ratio", type=float, default=0.90)

    clean_parser = subparsers.add_parser("clean", help="只清理 SVG")
    clean_parser.add_argument("svg_input", help="SVG 文件或文件夹")
    clean_parser.add_argument("-o", "--output-folder", default="./SVG_clean")
    clean_parser.add_argument("--min-background-area-ratio", type=float, default=0.90)

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        # 保留原来的直接运行行为。
        svg_folder = "./成品图"
        output_folder = "./PDF"
        svg_to_pdf(
            svg_folder,
            output_folder,
            crop_white_edges=True,
            clean_svg_folder=None,
        )
        return

    args = _build_arg_parser().parse_args(argv)

    if args.command == "pdf":
        svg_to_pdf(
            args.svg_input,
            args.output_folder,
            crop_white_edges=not args.no_crop,
            clean_svg_folder=args.clean_svg_folder,
            min_background_area_ratio=args.min_background_area_ratio,
        )
    elif args.command == "png":
        svg_to_png(
            args.svg_input,
            args.output_folder,
            dpi=args.dpi,
            crop_white_edges=not args.no_crop,
            clean_svg_folder=args.clean_svg_folder,
            min_background_area_ratio=args.min_background_area_ratio,
        )
    elif args.command == "clean":
        clean_svg(
            args.svg_input,
            output_folder=args.output_folder,
            min_background_area_ratio=args.min_background_area_ratio,
        )


# ============================================================
#   主程序入口 —— 在这里选择转换模式并设置参数
# ============================================================
if __name__ == "__main__":
    # 用法示例：
    # svg_to_pdf(svg_file="./图片1/example.svg", output_folder="./PDF")
    # svg_to_pdf(svg_folder="./图片1", output_folder="./PDF", clean_svg_folder=True)
    # svg_to_pdf(svg_file="./图片1/example.svg", output_folder="./PDF", clean_svg_folder="./SVG_clean")
    # svg_to_png(svg_folder="./图片1", output_folder="./PNG", dpi=600)
    # clean_svg(svg_input="./图片1/example.svg", output_folder="./SVG_clean")
    svg_to_pdf(svg_file="./图片1.svg", output_folder="./PDF")
