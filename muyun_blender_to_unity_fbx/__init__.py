# -*- coding: utf-8 -*-
bl_info = {
    "name": "木云 - Blender 到 Unity FBX",
    "author": "muyun",
    "version": (1, 0, 0),
    "blender": (3, 2, 0),
    "location": "文件 > 导出 > 木云 Unity FBX / 3D视图侧栏 > Unity导出",
    "description": "导出 Unity 友好的 FBX，并保留材质贴图与 Unity 材质重建数据。",
    "category": "Import-Export",
}

import json
import math
import os
import re
import shutil
import traceback
from datetime import datetime

import bpy
import mathutils
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ExportHelper


ADDON_VERSION = "1.0"
PACKAGE_BUILD = "1.0.002"
MAINTAINER = "muyun"
UNITY_IMPORTER_NAME = "MuyunBlenderUnityFbxPostprocessor.cs"
EXPORTABLE_TYPES = {"EMPTY", "MESH", "ARMATURE", "FONT", "CURVE", "SURFACE", "CAMERA", "LIGHT"}


UNITY_VERSION_ITEMS = (
    ("AUTO", "自动/通用", "使用通用 FBX 和材质清单，适合不确定版本时使用"),
    ("2019", "Unity 2019 LTS", "面向 Unity 2019 LTS 的导入设置"),
    ("2020", "Unity 2020 LTS", "面向 Unity 2020 LTS 的导入设置"),
    ("2021", "Unity 2021 LTS", "面向 Unity 2021 LTS 的导入设置"),
    ("2022", "Unity 2022 LTS", "面向 Unity 2022 LTS 的导入设置"),
    ("2023", "Unity 2023 LTS", "面向 Unity 2023 LTS 的导入设置"),
    ("6000", "Unity 6", "面向 Unity 6 / 6000.x 的导入设置"),
)


SCOPE_ITEMS = (
    ("SCENE", "整个场景", "导出当前场景中可导出的对象"),
    ("SELECTED", "选中对象", "只导出当前选中对象，可包含子级"),
    ("ACTIVE_COLLECTION", "活动集合", "导出活动集合中的对象"),
)


def safe_report(operator, level, message):
    if operator:
        operator.report({level}, message)
    print("[Muyun Unity FBX]", level, message)


def sanitize_filename(value, fallback="Asset"):
    value = value or fallback
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = value.strip(" .")
    return value or fallback


def norm_path(path):
    return os.path.normpath(bpy.path.abspath(path)) if path else ""


def unity_asset_path(path, assets_dir):
    if not path or not assets_dir:
        return ""
    path = os.path.normcase(os.path.abspath(path))
    assets_dir = os.path.normcase(os.path.abspath(assets_dir))
    if path == assets_dir or path.startswith(assets_dir + os.sep):
        rel = os.path.relpath(path, os.path.dirname(assets_dir))
        return rel.replace("\\", "/")
    return ""


def find_assets_dir_from_path(path):
    if not path:
        return ""

    current = os.path.abspath(path)
    if os.path.isfile(current):
        current = os.path.dirname(current)

    while True:
        if os.path.basename(current).lower() == "assets":
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        current = parent


def resolve_export_filepath(context, settings, override_filepath=""):
    if override_filepath:
        filepath = norm_path(override_filepath)
        if not filepath.lower().endswith(".fbx"):
            filepath += ".fbx"
        return filepath

    export_name = sanitize_filename(settings.export_name, default_export_name(context))
    if not export_name.lower().endswith(".fbx"):
        export_name += ".fbx"

    target = norm_path(settings.unity_project_path)
    if target:
        target_name = os.path.basename(os.path.normpath(target)).lower()
        if target_name == "assets":
            assets_dir = target
            subfolder = settings.export_subfolder.strip().replace("\\", "/").strip("/")
            if subfolder.lower().startswith("assets/"):
                export_dir = os.path.join(os.path.dirname(assets_dir), subfolder)
            elif subfolder and subfolder.lower() != "assets":
                export_dir = os.path.join(assets_dir, subfolder)
            else:
                export_dir = assets_dir
        elif os.path.isdir(os.path.join(target, "Assets")):
            subfolder = settings.export_subfolder.strip().replace("\\", "/").strip("/")
            if not subfolder:
                subfolder = "Assets/BlenderExports"
            export_dir = os.path.join(target, subfolder)
        else:
            export_dir = target
    else:
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else bpy.app.tempdir
        export_dir = os.path.join(blend_dir, "UnityExports")

    os.makedirs(export_dir, exist_ok=True)
    return os.path.join(export_dir, export_name)


def default_export_name(context):
    if bpy.data.filepath:
        return os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    if context.scene.name:
        return context.scene.name
    return "BlenderUnityExport"


def iter_collection_objects(collection, include_children=True):
    seen = set()
    for obj in collection.objects:
        if obj.name not in seen:
            seen.add(obj.name)
            yield obj
    if include_children:
        for child in collection.children:
            for obj in iter_collection_objects(child, include_children=True):
                if obj.name not in seen:
                    seen.add(obj.name)
                    yield obj


def add_children_recursive(obj, result, seen):
    for child in obj.children:
        if child.name not in seen:
            seen.add(child.name)
            result.append(child)
        add_children_recursive(child, result, seen)


def get_export_objects(context, settings):
    objects = []
    seen = set()

    if settings.selection_scope == "SELECTED":
        source = list(context.selected_objects)
        for obj in source:
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)
            if settings.include_children:
                add_children_recursive(obj, objects, seen)
    elif settings.selection_scope == "ACTIVE_COLLECTION":
        collection = context.collection
        source = iter_collection_objects(collection, include_children=settings.include_collection_children)
        for obj in source:
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)
    else:
        for obj in context.scene.objects:
            if obj.name not in seen:
                seen.add(obj.name)
                objects.append(obj)

    return [obj for obj in objects if obj.type in EXPORTABLE_TYPES]


def get_view_layer_names(context):
    return {obj.name for obj in context.view_layer.objects}


def unhide_collections(layer_collection, hidden_collections, disabled_collections):
    if layer_collection.exclude:
        return

    for child in layer_collection.children:
        if not child.exclude and child.hide_viewport:
            child.hide_viewport = False
            hidden_collections.append(child)
        if not child.exclude and child.collection.hide_viewport:
            child.collection.hide_viewport = False
            disabled_collections.append(child)
        unhide_collections(child, hidden_collections, disabled_collections)


def unhide_objects(context, hidden_objects, disabled_objects):
    view_layer_names = get_view_layer_names(context)
    for obj in bpy.data.objects:
        if obj.name not in view_layer_names:
            continue
        if obj.hide_get():
            obj.hide_set(False)
            hidden_objects.append(obj)
        if obj.hide_viewport:
            obj.hide_viewport = False
            disabled_objects.append(obj)


def make_single_user_data(export_objects, shared_data):
    for obj in export_objects:
        if not obj.data or obj.data.users <= 1:
            continue

        users = [user for user in bpy.data.objects if user.data == obj.data]
        if len(users) <= 1:
            continue

        if obj.type == "MESH":
            visible_modifiers = sum(len([mod for mod in user.modifiers if mod.show_viewport]) for user in users)
            if visible_modifiers == 0:
                shared_data[obj.name] = obj.data

        obj.data = obj.data.copy()


def apply_object_modifiers(context, export_objects):
    view_layer_names = get_view_layer_names(context)
    bpy.ops.object.select_all(action="DESELECT")

    for obj in export_objects:
        if obj.name not in view_layer_names:
            continue
        if obj.type not in {"MESH", "CURVE", "FONT", "SURFACE"}:
            continue
        if any(mod.type == "ARMATURE" for mod in obj.modifiers):
            continue
        obj.select_set(True)

    if context.selected_objects and bpy.ops.object.convert.poll():
        bpy.ops.object.convert(target="MESH")


def reset_parent_inverse(obj):
    if obj.parent:
        mat_world = obj.matrix_world.copy()
        obj.matrix_parent_inverse.identity()
        obj.matrix_basis = obj.parent.matrix_world.inverted() @ mat_world


def apply_rotation(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)


def fix_object_for_unity(obj, export_names):
    if obj.name in export_names:
        reset_parent_inverse(obj)
        original = obj.matrix_local.copy()
        obj.matrix_local = mathutils.Matrix.Rotation(math.radians(-90.0), 4, "X")
        apply_rotation(obj)
        obj.matrix_local = original @ mathutils.Matrix.Rotation(math.radians(90.0), 4, "X")

    for child in obj.children:
        if child.name in export_names:
            fix_object_for_unity(child, export_names)


def select_export_objects(context, export_objects):
    bpy.ops.object.select_all(action="DESELECT")
    view_layer_names = get_view_layer_names(context)
    first = None
    for obj in export_objects:
        if obj.name in view_layer_names:
            obj.select_set(True)
            if first is None:
                first = obj
    if first:
        context.view_layer.objects.active = first


def socket_default(socket, fallback):
    if socket is None:
        return fallback
    value = getattr(socket, "default_value", fallback)
    try:
        return list(value)
    except TypeError:
        return value


def find_principled_node(material):
    if not material or not material.use_nodes or not material.node_tree:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled" or node.type == "BSDF_PRINCIPLED":
            return node
    return None


def first_socket(node, names):
    if not node:
        return None
    for name in names:
        socket = node.inputs.get(name)
        if socket:
            return socket
    return None


def find_image_from_socket(socket, visited=None):
    if socket is None or not socket.is_linked:
        return None
    if visited is None:
        visited = set()

    for link in socket.links:
        node = link.from_node
        if node in visited:
            continue
        visited.add(node)

        if node.bl_idname == "ShaderNodeTexImage":
            return node.image

        for input_socket in getattr(node, "inputs", []):
            image = find_image_from_socket(input_socket, visited)
            if image:
                return image

    return None


def collect_all_material_images(material):
    images = []
    if not material or not material.use_nodes or not material.node_tree:
        return images
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and node.image:
            images.append(node.image)
    return images


def image_original_path(image):
    if not image:
        return ""
    filepath = image.filepath_raw or image.filepath
    if not filepath:
        return ""
    try:
        return bpy.path.abspath(filepath, library=image.library)
    except TypeError:
        return bpy.path.abspath(filepath)


def unique_path(folder, basename):
    name, ext = os.path.splitext(basename)
    candidate = os.path.join(folder, basename)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{name}_{index}{ext}")
        index += 1
    return candidate


def save_or_copy_image(image, texture_dir, role, used_image_ids, warnings):
    if not image:
        return None

    image_key = str(image.as_pointer())
    if image_key in used_image_ids:
        return used_image_ids[image_key]

    os.makedirs(texture_dir, exist_ok=True)
    original = image_original_path(image)
    original_exists = bool(original and os.path.exists(original) and os.path.isfile(original))
    ext = os.path.splitext(original)[1].lower() if original_exists else ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp", ".exr", ".hdr", ".psd"}:
        ext = ".png"

    stem = sanitize_filename(os.path.splitext(os.path.basename(original))[0] if original else image.name, "Texture")
    target = unique_path(texture_dir, f"{stem}{ext}")

    if original_exists and not image.packed_file and image.source != "GENERATED":
        shutil.copy2(original, target)
    else:
        target = os.path.splitext(target)[0] + ".png"
        try:
            image.save_render(target)
        except Exception:
            old_path = image.filepath_raw
            old_format = image.file_format
            try:
                image.filepath_raw = target
                image.file_format = "PNG"
                image.save()
            except Exception as exc:
                warnings.append(f"贴图 {image.name} 无法保存：{exc}")
                return None
            finally:
                image.filepath_raw = old_path
                image.file_format = old_format

    texture_id = f"tex_{len(used_image_ids) + 1:03d}"
    record = {
        "id": texture_id,
        "name": image.name,
        "role": role or "extra",
        "absolutePath": target,
        "originalPath": original,
    }
    used_image_ids[image_key] = record
    return record


def material_to_manifest(material, texture_dir, export_dir, assets_dir, used_images, warnings):
    principled = find_principled_node(material)
    base_color = [1.0, 1.0, 1.0, 1.0]
    metallic = 0.0
    roughness = 0.5
    alpha = 1.0

    if material:
        base_color = list(getattr(material, "diffuse_color", base_color))

    sockets = {}
    if principled:
        sockets = {
            "baseColorTexture": first_socket(principled, ["Base Color", "BaseColor"]),
            "normalTexture": first_socket(principled, ["Normal"]),
            "metallicTexture": first_socket(principled, ["Metallic"]),
            "roughnessTexture": first_socket(principled, ["Roughness"]),
            "alphaTexture": first_socket(principled, ["Alpha"]),
            "emissionTexture": first_socket(principled, ["Emission Color", "Emission"]),
            "occlusionTexture": first_socket(principled, ["Ambient Occlusion", "Occlusion"]),
        }
        base_color = socket_default(sockets["baseColorTexture"], base_color)
        metallic = float(socket_default(sockets["metallicTexture"], metallic) or 0.0)
        roughness = float(socket_default(sockets["roughnessTexture"], roughness) or 0.5)
        alpha = float(socket_default(sockets["alphaTexture"], alpha) or 1.0)

    texture_refs = {}
    role_by_field = {
        "baseColorTexture": "baseColor",
        "normalTexture": "normal",
        "metallicTexture": "metallic",
        "roughnessTexture": "roughness",
        "occlusionTexture": "occlusion",
        "emissionTexture": "emission",
    }

    for field, role in role_by_field.items():
        image = find_image_from_socket(sockets.get(field)) if sockets else None
        record = save_or_copy_image(image, texture_dir, role, used_images, warnings)
        texture_refs[field] = record["id"] if record else ""

    extra_ids = []
    for image in collect_all_material_images(material):
        record = save_or_copy_image(image, texture_dir, "extra", used_images, warnings)
        if record and record["id"] not in texture_refs.values() and record["id"] not in extra_ids:
            extra_ids.append(record["id"])

    def channel(index, fallback=1.0):
        try:
            return float(base_color[index])
        except Exception:
            return fallback

    return {
        "name": material.name if material else "Material",
        "baseColor": {
            "r": channel(0),
            "g": channel(1),
            "b": channel(2),
            "a": channel(3),
        },
        "metallic": metallic,
        "roughness": roughness,
        "alpha": alpha,
        "baseColorTexture": texture_refs.get("baseColorTexture", ""),
        "normalTexture": texture_refs.get("normalTexture", ""),
        "metallicTexture": texture_refs.get("metallicTexture", ""),
        "roughnessTexture": texture_refs.get("roughnessTexture", ""),
        "occlusionTexture": texture_refs.get("occlusionTexture", ""),
        "emissionTexture": texture_refs.get("emissionTexture", ""),
        "extraTextures": extra_ids,
    }


def build_material_manifest(export_objects, filepath, settings):
    export_dir = os.path.dirname(filepath)
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    texture_dir = os.path.join(export_dir, f"{base_name}_Textures")
    assets_dir = find_assets_dir_from_path(filepath)
    used_images = {}
    warnings = []
    material_records = []
    seen_materials = set()

    for obj in export_objects:
        for slot in getattr(obj, "material_slots", []):
            material = slot.material
            if not material or material.name in seen_materials:
                continue
            seen_materials.add(material.name)
            material_records.append(material_to_manifest(material, texture_dir, export_dir, assets_dir, used_images, warnings))

    texture_records = []
    for record in used_images.values():
        absolute = record["absolutePath"]
        texture_records.append({
            "id": record["id"],
            "name": record["name"],
            "role": record["role"],
            "assetPath": unity_asset_path(absolute, assets_dir),
            "relativePath": os.path.relpath(absolute, export_dir).replace("\\", "/"),
            "originalPath": record["originalPath"],
        })

    manifest = {
        "addonVersion": ADDON_VERSION,
        "packageBuild": PACKAGE_BUILD,
        "maintainer": MAINTAINER,
        "unityVersion": settings.unity_version,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "fbxFile": os.path.basename(filepath),
        "materials": material_records,
        "textures": texture_records,
        "warnings": warnings,
    }

    manifest_path = os.path.splitext(filepath)[0] + ".muyun_unity.json"
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    return manifest_path, texture_records, warnings


def install_unity_importer(filepath):
    assets_dir = find_assets_dir_from_path(filepath)
    if not assets_dir:
        return ""

    editor_dir = os.path.join(assets_dir, "Editor")
    os.makedirs(editor_dir, exist_ok=True)

    source = os.path.join(os.path.dirname(__file__), "unity", "Editor", UNITY_IMPORTER_NAME)
    target = os.path.join(editor_dir, UNITY_IMPORTER_NAME)
    if os.path.exists(source):
        shutil.copy2(source, target)
        return target
    return ""


def perform_export(context, settings, filepath, operator=None):
    filepath = resolve_export_filepath(context, settings, filepath)
    export_objects = get_export_objects(context, settings)
    if not export_objects:
        safe_report(operator, "WARNING", "没有找到可导出的对象。")
        return {"CANCELLED"}

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    export_names = {obj.name for obj in export_objects}
    root_objects = [obj for obj in export_objects if not obj.parent or obj.parent.name not in export_names]

    shared_data = {}
    hidden_collections = []
    hidden_objects = []
    disabled_collections = []
    disabled_objects = []
    selection = list(context.selected_objects)
    active = context.view_layer.objects.active
    previous_mode = context.mode

    manifest_path = ""
    importer_path = ""

    try:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.ed.undo_push(message="Muyun Unity FBX Prepare")

        unhide_collections(context.view_layer.layer_collection, hidden_collections, disabled_collections)
        unhide_objects(context, hidden_objects, disabled_objects)
        make_single_user_data(export_objects, shared_data)

        if settings.apply_modifiers:
            apply_object_modifiers(context, export_objects)
            export_objects = [bpy.data.objects[name] for name in export_names if name in bpy.data.objects]
            export_names = {obj.name for obj in export_objects}
            root_objects = [obj for obj in export_objects if not obj.parent or obj.parent.name not in export_names]

        for obj in root_objects:
            fix_object_for_unity(obj, export_names)

        for name, data in shared_data.items():
            if name in bpy.data.objects:
                bpy.data.objects[name].data = data

        context.view_layer.update()
        select_export_objects(context, export_objects)

        if settings.copy_textures or settings.write_manifest:
            manifest_path, texture_records, warnings = build_material_manifest(export_objects, filepath, settings)
            for warning in warnings:
                safe_report(operator, "WARNING", warning)

        params = {
            "filepath": filepath,
            "use_selection": True,
            "use_custom_props": True,
            "object_types": {"EMPTY", "MESH", "ARMATURE", "CAMERA", "LIGHT"},
            "apply_scale_options": "FBX_SCALE_UNITS",
            "add_leaf_bones": settings.add_leaf_bones,
            "use_armature_deform_only": settings.only_deform_bones,
            "primary_bone_axis": "Y",
            "secondary_bone_axis": "X",
            "use_tspace": settings.export_tangents,
            "use_triangles": settings.triangulate_faces,
            "bake_anim": settings.export_animations,
        }

        if settings.copy_textures or settings.embed_textures:
            params["path_mode"] = "COPY"
        if settings.embed_textures:
            params["embed_textures"] = True

        bpy.ops.export_scene.fbx(**params)

        if settings.install_unity_importer:
            importer_path = install_unity_importer(filepath)

    except Exception as exc:
        traceback.print_exc()
        safe_report(operator, "ERROR", f"导出失败：{exc}")
        return {"CANCELLED"}
    finally:
        try:
            bpy.ops.ed.undo_push(message="")
            bpy.ops.ed.undo()
            bpy.ops.ed.undo_push(message="Muyun Unity FBX Export")
        except Exception:
            pass

        for obj in hidden_objects:
            if obj.name in bpy.data.objects:
                obj.hide_set(True)
        for obj in disabled_objects:
            if obj.name in bpy.data.objects:
                obj.hide_viewport = True
        for collection in hidden_collections:
            collection.hide_viewport = True
        for collection in disabled_collections:
            collection.collection.hide_viewport = True

        try:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in selection:
                if obj.name in bpy.data.objects:
                    bpy.data.objects[obj.name].select_set(True)
            if active and active.name in bpy.data.objects:
                context.view_layer.objects.active = bpy.data.objects[active.name]
            if previous_mode != "OBJECT" and bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode=previous_mode.split("_")[0])
        except Exception:
            pass

    context.scene.muyun_unity_export.last_export_path = filepath
    context.scene.muyun_unity_export.last_manifest_path = manifest_path
    context.scene.muyun_unity_export.last_importer_path = importer_path
    safe_report(operator, "INFO", f"已导出：{filepath}")
    return {"FINISHED"}


class MUYUN_UnityExportSettings(PropertyGroup):
    unity_version: EnumProperty(
        name="Unity 版本",
        description="选择目标 Unity 版本。FBX 使用通用格式，版本用于导入辅助和记录。",
        items=UNITY_VERSION_ITEMS,
        default="AUTO",
    )
    unity_project_path: StringProperty(
        name="Unity 项目或 Assets 目录",
        description="可选择 Unity 项目根目录，也可直接选择 Assets 目录。",
        subtype="DIR_PATH",
        default="",
    )
    export_subfolder: StringProperty(
        name="导出子目录",
        description="当选择 Unity 项目根目录时使用，默认导出到 Assets/BlenderExports。",
        default="Assets/BlenderExports",
    )
    export_name: StringProperty(
        name="导出文件名",
        description="不填写时使用当前 blend 文件名或场景名。",
        default="",
    )
    selection_scope: EnumProperty(
        name="导出范围",
        items=SCOPE_ITEMS,
        default="SCENE",
    )
    include_children: BoolProperty(
        name="选中对象包含子级",
        default=True,
    )
    include_collection_children: BoolProperty(
        name="集合包含子集合",
        default=True,
    )
    apply_modifiers: BoolProperty(
        name="应用可见修改器",
        description="导出前临时应用非骨骼修改器，场景会自动恢复。",
        default=True,
    )
    triangulate_faces: BoolProperty(
        name="三角化面",
        description="提高 Unity 切线与法线导入稳定性。",
        default=True,
    )
    export_tangents: BoolProperty(
        name="导出切线",
        default=True,
    )
    export_animations: BoolProperty(
        name="导出动画",
        default=True,
    )
    only_deform_bones: BoolProperty(
        name="仅导出变形骨骼",
        default=False,
    )
    add_leaf_bones: BoolProperty(
        name="添加末端骨骼",
        default=False,
    )
    copy_textures: BoolProperty(
        name="复制贴图文件",
        default=True,
    )
    embed_textures: BoolProperty(
        name="同时嵌入贴图到 FBX",
        description="不同 Unity 版本对嵌入贴图兼容性不完全一致，建议保留复制贴图。",
        default=False,
    )
    write_manifest: BoolProperty(
        name="生成材质清单",
        default=True,
    )
    install_unity_importer: BoolProperty(
        name="自动安装 Unity 导入辅助脚本",
        description="导出到 Assets 内时写入 Assets/Editor/MuyunBlenderUnityFbxPostprocessor.cs。",
        default=True,
    )
    last_export_path: StringProperty(name="最近导出", default="")
    last_manifest_path: StringProperty(name="最近清单", default="")
    last_importer_path: StringProperty(name="最近 Unity 脚本", default="")


class MUYUN_OT_quick_export_unity_fbx(Operator):
    bl_idname = "export_scene.muyun_unity_fbx_quick"
    bl_label = "直接导出到 Unity 目录"
    bl_description = "按面板设置直接导出 FBX"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.muyun_unity_export
        return perform_export(context, settings, "", self)


class MUYUN_OT_export_unity_fbx_as(Operator, ExportHelper):
    bl_idname = "export_scene.muyun_unity_fbx"
    bl_label = "木云 Unity FBX"
    bl_description = "导出 Unity 友好的 FBX，并生成材质贴图清单"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})

    def invoke(self, context, event):
        settings = context.scene.muyun_unity_export
        self.filepath = resolve_export_filepath(context, settings, "")
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        settings = context.scene.muyun_unity_export
        return perform_export(context, settings, self.filepath, self)


class MUYUN_PT_unity_export_panel(Panel):
    bl_label = "Blender 到 Unity"
    bl_idname = "MUYUN_PT_unity_export_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Unity导出"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.muyun_unity_export

        layout.label(text=f"版本 {ADDON_VERSION}  维护者 {MAINTAINER}")
        layout.prop(settings, "unity_version")
        layout.prop(settings, "unity_project_path")
        layout.prop(settings, "export_subfolder")
        layout.prop(settings, "export_name")

        layout.separator()
        layout.prop(settings, "selection_scope")
        if settings.selection_scope == "SELECTED":
            layout.prop(settings, "include_children")
        if settings.selection_scope == "ACTIVE_COLLECTION":
            layout.prop(settings, "include_collection_children")

        layout.separator()
        layout.prop(settings, "apply_modifiers")
        layout.prop(settings, "triangulate_faces")
        layout.prop(settings, "export_tangents")
        layout.prop(settings, "export_animations")
        layout.prop(settings, "only_deform_bones")
        layout.prop(settings, "add_leaf_bones")

        layout.separator()
        layout.prop(settings, "copy_textures")
        layout.prop(settings, "embed_textures")
        layout.prop(settings, "write_manifest")
        layout.prop(settings, "install_unity_importer")

        layout.separator()
        row = layout.row(align=True)
        row.operator(MUYUN_OT_quick_export_unity_fbx.bl_idname, icon="EXPORT")
        row.operator(MUYUN_OT_export_unity_fbx_as.bl_idname, text="另存为", icon="FILE_FOLDER")

        if settings.last_export_path:
            layout.separator()
            layout.label(text="最近导出：")
            layout.label(text=settings.last_export_path, icon="FILE_TICK")


def menu_func_export(self, context):
    self.layout.operator(MUYUN_OT_export_unity_fbx_as.bl_idname, text="木云 Unity FBX (.fbx)")


classes = (
    MUYUN_UnityExportSettings,
    MUYUN_OT_quick_export_unity_fbx,
    MUYUN_OT_export_unity_fbx_as,
    MUYUN_PT_unity_export_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.muyun_unity_export = PointerProperty(type=MUYUN_UnityExportSettings)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    del bpy.types.Scene.muyun_unity_export
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
