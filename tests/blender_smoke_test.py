import json
import os
import sys

import bpy


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDON_PARENT = BASE_DIR
ADDON_NAME = "muyun_blender_to_unity_fbx"
OUT_DIR = os.path.join(BASE_DIR, "test_output", "UnityProject")
ASSETS_DIR = os.path.join(OUT_DIR, "Assets")


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def make_image(path, name, color):
    image = bpy.data.images.new(name, width=8, height=8, alpha=True)
    pixels = []
    for _ in range(64):
        pixels.extend(color)
    image.pixels[:] = pixels
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()
    return image


def make_scene():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, "ProjectSettings"), exist_ok=True)
    texture_source = os.path.join(BASE_DIR, "test_output", "source_textures")
    os.makedirs(texture_source, exist_ok=True)

    base_image = make_image(os.path.join(texture_source, "base_color.png"), "Muyun_Base_Color", [0.15, 0.55, 0.95, 1.0])
    normal_image = make_image(os.path.join(texture_source, "normal.png"), "Muyun_Normal", [0.5, 0.5, 1.0, 1.0])

    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.object
    cube.name = "Muyun_Test_Cube"

    material = bpy.data.materials.new("Muyun_Test_Material")
    material.use_nodes = True
    material.diffuse_color = [0.15, 0.55, 0.95, 1.0]
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")

    base_node = nodes.new(type="ShaderNodeTexImage")
    base_node.image = base_image
    links.new(base_node.outputs["Color"], bsdf.inputs["Base Color"])

    normal_node = nodes.new(type="ShaderNodeTexImage")
    normal_node.image = normal_image
    normal_map = nodes.new(type="ShaderNodeNormalMap")
    links.new(normal_node.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    cube.data.materials.append(material)

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    empty = bpy.context.object
    empty.name = "Muyun_Root"
    cube.parent = empty


def load_addon():
    sys.path.insert(0, ADDON_PARENT)
    addon = __import__(ADDON_NAME)
    addon.register()
    return addon


def run_export():
    settings = bpy.context.scene.muyun_unity_export
    settings.unity_version = "2022"
    settings.unity_project_path = OUT_DIR
    settings.export_subfolder = "Assets/BlenderExports"
    settings.export_name = "muyun_smoke"
    settings.selection_scope = "SCENE"
    settings.copy_textures = True
    settings.write_manifest = True
    settings.install_unity_importer = True
    settings.triangulate_faces = True
    settings.export_tangents = True
    result = bpy.ops.export_scene.muyun_unity_fbx_quick()
    if "FINISHED" not in result:
        raise RuntimeError("Export operator did not finish")


def assert_outputs():
    fbx = os.path.join(ASSETS_DIR, "BlenderExports", "muyun_smoke.fbx")
    manifest = os.path.join(ASSETS_DIR, "BlenderExports", "muyun_smoke.muyun_unity.json")
    texture_dir = os.path.join(ASSETS_DIR, "BlenderExports", "muyun_smoke_Textures")
    importer = os.path.join(ASSETS_DIR, "Editor", "MuyunBlenderUnityFbxPostprocessor.cs")

    for path in [fbx, manifest, texture_dir, importer]:
        if not os.path.exists(path):
            raise AssertionError(f"Missing expected output: {path}")

    with open(manifest, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data["unityVersion"] != "2022":
        raise AssertionError("Unity version was not written to manifest")
    if not data["materials"]:
        raise AssertionError("No materials in manifest")
    if len(data["textures"]) < 2:
        raise AssertionError("Expected at least base color and normal textures")
    if not data["materials"][0]["baseColorTexture"]:
        raise AssertionError("Base color texture was not mapped")
    if not data["materials"][0]["normalTexture"]:
        raise AssertionError("Normal texture was not mapped")


def main():
    reset_scene()
    make_scene()
    load_addon()
    run_export()
    assert_outputs()
    print("MUYUN_SMOKE_TEST_OK")


if __name__ == "__main__":
    main()
