# 木云 Blender 到 Unity FBX 导出插件

版本：1.0  
维护者：muyun  
当前打包编号：1.0.002

这是一个中文 Blender 插件，用于把 Blender 场景导出为 Unity 友好的 FBX，并尽量完整保留材质、贴图和 Unity 导入所需的附属数据。

## 功能

- 导出 Unity 坐标和比例友好的 FBX。
- 可选择目标 Unity 版本：自动、2019 LTS、2020 LTS、2021 LTS、2022 LTS、2023 LTS、Unity 6。
- 支持整个场景、选中对象、活动集合导出。
- 支持导出动画、切线、三角化、骨骼选项和临时应用可见修改器。
- 自动复制贴图到 Unity 资源目录旁的 `_Textures` 文件夹。
- 生成 `.muyun_unity.json` 材质清单，记录材质名、颜色、金属度、粗糙度、法线、遮挡、发光和贴图路径。
- 可自动安装 Unity 导入辅助脚本到 `Assets/Editor`，用于生成 `.mat` 材质并绑定贴图。

## 下载与安装

直接下载：

- Blender 插件安装包：`release/muyun_blender_to_unity_fbx_addon_v1.0.002.zip`
- 完整工程包：`release/muyun_blender_to_unity_fbx_project_v1.0.002.zip`

在 Blender 中打开：

1. `编辑 > 偏好设置 > 插件 > 安装`
2. 选择 `release/muyun_blender_to_unity_fbx_addon_v1.0.002.zip`
3. 启用“木云 - Blender 到 Unity FBX”

## 使用

1. 在 Blender 右侧栏打开“Unity导出”。
2. 选择目标 Unity 版本和 Unity 项目目录，或直接选择项目内的 `Assets` 目录。
3. 设置导出文件名和导出范围。
4. 点击“直接导出到 Unity 目录”，或使用 `文件 > 导出 > 木云 Unity FBX (.fbx)`。
5. 在 Unity 中等待资源刷新。导入辅助脚本会生成 `_Materials` 文件夹并绑定材质贴图。

## 项目结构

- `muyun_blender_to_unity_fbx/`：Blender 插件源码。
- `unity/Editor/`：Unity 导入辅助脚本。
- `tests/`：Blender 后台烟测脚本。
- `docs/`：变更记录和验证说明。
- `release/`：已打包的可安装插件和完整工程包。

## 已验证

- Blender 5.1.2 后台导出测试通过。
- Blender 5.1.2 从 zip 安装并启用通过。
- Unity 2022.3.22f1 批处理导入通过，生成材质并绑定基础贴图和法线贴图。
- Unity 6000.3.12f1 批处理导入通过，生成材质并绑定基础贴图和法线贴图。

详见 `docs/验证说明_1.0.002.md`。

## 注意

FBX 本身无法完整表达 Blender 的所有节点材质。本插件通过“FBX + 外部贴图 + 材质清单 + Unity 导入脚本”组合方式降低数据丢失风险。复杂节点、程序纹理、几何节点材质建议先在 Blender 中烘焙成图片贴图再导出。
