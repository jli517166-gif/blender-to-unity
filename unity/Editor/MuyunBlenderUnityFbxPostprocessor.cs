using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEngine;

// Muyun Blender -> Unity FBX importer helper.
// Put this file under Assets/Editor. The Blender add-on can install it automatically.
public sealed class MuyunBlenderUnityFbxPostprocessor : AssetPostprocessor
{
    private const string ManifestSuffix = ".muyun_unity.json";

    private void OnPreprocessModel()
    {
        if (!assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        ModelImporter importer = assetImporter as ModelImporter;
        if (importer == null)
        {
            return;
        }

        importer.globalScale = 1.0f;
        importer.importNormals = ModelImporterNormals.Import;
        importer.importTangents = ModelImporterTangents.Import;

#if UNITY_2019_1_OR_NEWER
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        importer.materialLocation = ModelImporterMaterialLocation.External;
#endif
    }

    private static void OnPostprocessAllAssets(
        string[] importedAssets,
        string[] deletedAssets,
        string[] movedAssets,
        string[] movedFromAssetPaths)
    {
        bool changed = false;

        foreach (string importedAsset in importedAssets)
        {
            if (!importedAsset.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            changed |= ProcessModel(importedAsset);
        }

        if (changed)
        {
            AssetDatabase.SaveAssets();
        }
    }

    private static bool ProcessModel(string modelPath)
    {
        string manifestPath = Path.ChangeExtension(modelPath, ManifestSuffix);
        TextAsset manifestAsset = AssetDatabase.LoadAssetAtPath<TextAsset>(manifestPath);
        if (manifestAsset == null)
        {
            return false;
        }

        ExportManifest manifest = JsonUtility.FromJson<ExportManifest>(manifestAsset.text);
        if (manifest == null || manifest.materials == null)
        {
            return false;
        }

        string modelDirectory = NormalizeAssetPath(Path.GetDirectoryName(modelPath));
        string materialDirectory = modelDirectory + "/" + Path.GetFileNameWithoutExtension(modelPath) + "_Materials";
        EnsureAssetFolder(materialDirectory);

        Dictionary<string, TextureEntry> texturesById = BuildTextureMap(manifest);
        ModelImporter importer = AssetImporter.GetAtPath(modelPath) as ModelImporter;
        if (importer == null)
        {
            return false;
        }

        bool changed = false;

        foreach (MaterialEntry sourceMaterial in manifest.materials)
        {
            if (sourceMaterial == null || string.IsNullOrEmpty(sourceMaterial.name))
            {
                continue;
            }

            Material material = LoadOrCreateMaterial(materialDirectory, sourceMaterial.name);
            if (material == null)
            {
                continue;
            }

            ApplyMaterialData(material, sourceMaterial, texturesById, modelDirectory);

            AssetImporter.SourceAssetIdentifier identifier = new AssetImporter.SourceAssetIdentifier(typeof(Material), sourceMaterial.name);
            Dictionary<AssetImporter.SourceAssetIdentifier, UnityEngine.Object> remaps = importer.GetExternalObjectMap();
            UnityEngine.Object current;
            if (!remaps.TryGetValue(identifier, out current) || current != material)
            {
                importer.AddRemap(identifier, material);
                changed = true;
            }
        }

        if (changed)
        {
            importer.SaveAndReimport();
        }

        return changed;
    }

    private static Dictionary<string, TextureEntry> BuildTextureMap(ExportManifest manifest)
    {
        Dictionary<string, TextureEntry> result = new Dictionary<string, TextureEntry>();
        if (manifest.textures == null)
        {
            return result;
        }

        foreach (TextureEntry texture in manifest.textures)
        {
            if (texture != null && !string.IsNullOrEmpty(texture.id))
            {
                result[texture.id] = texture;
            }
        }

        return result;
    }

    private static Material LoadOrCreateMaterial(string materialDirectory, string materialName)
    {
        string assetName = SanitizeAssetName(materialName) + ".mat";
        string materialPath = materialDirectory + "/" + assetName;
        Material material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
        Shader shader = FindBestShader();

        if (material == null)
        {
            material = new Material(shader != null ? shader : Shader.Find("Standard"));
            material.name = materialName;
            AssetDatabase.CreateAsset(material, materialPath);
        }
        else if (shader != null && material.shader != shader)
        {
            material.shader = shader;
        }

        return material;
    }

    private static Shader FindBestShader()
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader != null)
        {
            return shader;
        }

        shader = Shader.Find("HDRP/Lit");
        if (shader != null)
        {
            return shader;
        }

        return Shader.Find("Standard");
    }

    private static void ApplyMaterialData(
        Material material,
        MaterialEntry source,
        Dictionary<string, TextureEntry> texturesById,
        string modelDirectory)
    {
        Color color = source.baseColor != null
            ? new Color(source.baseColor.r, source.baseColor.g, source.baseColor.b, source.alpha <= 0.0f ? source.baseColor.a : source.alpha)
            : Color.white;

        SetColorIfExists(material, "_BaseColor", color);
        SetColorIfExists(material, "_Color", color);
        SetFloatIfExists(material, "_Metallic", Mathf.Clamp01(source.metallic));
        SetFloatIfExists(material, "_Smoothness", Mathf.Clamp01(1.0f - source.roughness));

        Texture2D baseMap = LoadTexture(source.baseColorTexture, texturesById, modelDirectory, false);
        SetTextureIfExists(material, "_BaseMap", baseMap);
        SetTextureIfExists(material, "_MainTex", baseMap);

        Texture2D normalMap = LoadTexture(source.normalTexture, texturesById, modelDirectory, true);
        SetTextureIfExists(material, "_BumpMap", normalMap);
        if (normalMap != null)
        {
            material.EnableKeyword("_NORMALMAP");
        }

        Texture2D metallicMap = LoadTexture(source.metallicTexture, texturesById, modelDirectory, false);
        SetTextureIfExists(material, "_MetallicGlossMap", metallicMap);
        SetTextureIfExists(material, "_MetallicMap", metallicMap);

        Texture2D occlusionMap = LoadTexture(source.occlusionTexture, texturesById, modelDirectory, false);
        SetTextureIfExists(material, "_OcclusionMap", occlusionMap);

        Texture2D emissionMap = LoadTexture(source.emissionTexture, texturesById, modelDirectory, false);
        SetTextureIfExists(material, "_EmissionMap", emissionMap);
        if (emissionMap != null)
        {
            material.EnableKeyword("_EMISSION");
        }

        EditorUtility.SetDirty(material);
    }

    private static Texture2D LoadTexture(
        string textureId,
        Dictionary<string, TextureEntry> texturesById,
        string modelDirectory,
        bool normalMap)
    {
        if (string.IsNullOrEmpty(textureId))
        {
            return null;
        }

        TextureEntry entry;
        if (!texturesById.TryGetValue(textureId, out entry))
        {
            return null;
        }

        string assetPath = entry.assetPath;
        if (string.IsNullOrEmpty(assetPath) && !string.IsNullOrEmpty(entry.relativePath))
        {
            assetPath = NormalizeAssetPath(modelDirectory + "/" + entry.relativePath);
        }

        if (string.IsNullOrEmpty(assetPath))
        {
            return null;
        }

        ConfigureTextureImporter(assetPath, normalMap, entry.role);
        return AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
    }

    private static void ConfigureTextureImporter(string assetPath, bool normalMap, string role)
    {
        TextureImporter importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
        if (importer == null)
        {
            return;
        }

        bool changed = false;
        TextureImporterType targetType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
        if (importer.textureType != targetType)
        {
            importer.textureType = targetType;
            changed = true;
        }

        bool shouldUseLinear = role == "metallic" || role == "roughness" || role == "occlusion" || role == "normal";
        if (importer.sRGBTexture == shouldUseLinear)
        {
            importer.sRGBTexture = !shouldUseLinear;
            changed = true;
        }

        if (changed)
        {
            importer.SaveAndReimport();
        }
    }

    private static void SetTextureIfExists(Material material, string propertyName, Texture texture)
    {
        if (texture != null && material.HasProperty(propertyName))
        {
            material.SetTexture(propertyName, texture);
        }
    }

    private static void SetColorIfExists(Material material, string propertyName, Color color)
    {
        if (material.HasProperty(propertyName))
        {
            material.SetColor(propertyName, color);
        }
    }

    private static void SetFloatIfExists(Material material, string propertyName, float value)
    {
        if (material.HasProperty(propertyName))
        {
            material.SetFloat(propertyName, value);
        }
    }

    private static void EnsureAssetFolder(string assetFolder)
    {
        assetFolder = NormalizeAssetPath(assetFolder);
        if (AssetDatabase.IsValidFolder(assetFolder))
        {
            return;
        }

        string[] parts = assetFolder.Split('/');
        string current = parts[0];
        for (int i = 1; i < parts.Length; i++)
        {
            string next = current + "/" + parts[i];
            if (!AssetDatabase.IsValidFolder(next))
            {
                AssetDatabase.CreateFolder(current, parts[i]);
            }
            current = next;
        }
    }

    private static string NormalizeAssetPath(string path)
    {
        return (path ?? string.Empty).Replace("\\", "/").TrimEnd('/');
    }

    private static string SanitizeAssetName(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "Material";
        }

        foreach (char invalid in Path.GetInvalidFileNameChars())
        {
            value = value.Replace(invalid, '_');
        }

        return value.Trim();
    }

    [Serializable]
    private sealed class ExportManifest
    {
        public string addonVersion;
        public string unityVersion;
        public MaterialEntry[] materials;
        public TextureEntry[] textures;
    }

    [Serializable]
    private sealed class MaterialEntry
    {
        public string name;
        public ColorData baseColor;
        public float metallic;
        public float roughness;
        public float alpha;
        public string baseColorTexture;
        public string normalTexture;
        public string metallicTexture;
        public string roughnessTexture;
        public string occlusionTexture;
        public string emissionTexture;
        public string[] extraTextures;
    }

    [Serializable]
    private sealed class TextureEntry
    {
        public string id;
        public string name;
        public string role;
        public string assetPath;
        public string relativePath;
        public string originalPath;
    }

    [Serializable]
    private sealed class ColorData
    {
        public float r;
        public float g;
        public float b;
        public float a;
    }
}
