bl_info = {
    "name": "Final Fantasy Tactics GNS Format",
    "author": "Christopher E. Moore",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "File > Import-Export",
    "description": "Import-Export GNS, Import GNS mesh, UVs, materials and textures",
    "warning": "",
    "doc_url": "github.com/thenumbernine",
    "support": 'OFFICIAL',
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "import_gns" in locals():
        importlib.reload(import_gns)


import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    StringProperty,
    EnumProperty,
)
from bpy_extras.io_utils import (
    ImportHelper,
    ExportHelper,
    orientation_helper,
    path_reference_mode,
    axis_conversion,
)


@orientation_helper(axis_forward='Z', axis_up='-Y')
class ImportGNS(bpy.types.Operator, ImportHelper):
    """Load a Final Fantasy Tactics GNS File"""
    bl_idname = "import_scene.gns"
    bl_label = "Import GNS"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".gns"
    filter_glob: StringProperty(
        default="*.gns",
        options={'HIDDEN'},
    )

    global_scale_x : FloatProperty(
        name = "Scale Down X",
        min=.01, max=1000.,
        default=28.0,
    )
    global_scale_y : FloatProperty(
        name = "Scale Down Y",
        min=.01, max=1000.,
        default=24.0,
    )
    global_scale_z : FloatProperty(
        name = "Scale Down Z",
        min=.01, max=1000.,
        default=28.0,
    )

    def execute(self, context):
        # print("Selected: " + context.active_object.name)
        from . import import_gns

        keywords = self.as_keywords(
            ignore=(
                "axis_forward",
                "axis_up",
                "filter_glob",
                "split_mode",
            ),
        )

        global_matrix = axis_conversion(
            from_forward=self.axis_forward,
            from_up=self.axis_up,
        ).to_4x4()
        keywords["global_matrix"] = global_matrix

        if bpy.data.is_saved and context.preferences.filepaths.use_relative_paths:
            import os
            keywords["relpath"] = os.path.dirname(bpy.data.filepath)

        return import_gns.load(context, **keywords)

    def draw(self, context):
        pass


class GNS_PT_import_include(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Include"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_gns"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator


class GNS_PT_import_transform(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Transform"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_gns"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")
        layout.prop(operator, "global_scale_x")
        layout.prop(operator, "global_scale_y")
        layout.prop(operator, "global_scale_z")


class GNS_PT_import_geometry(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Geometry"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_gns"

    def draw(self, context):
        layout = self.layout

        sfile = context.space_data
        operator = sfile.active_operator

        layout.row().prop(operator, "split_mode", expand=True)

        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

def menu_func_import(self, context):
    self.layout.operator(ImportGNS.bl_idname, text="Final Fantasy Tactics (.gns)")


classes = (
    ImportGNS,
    GNS_PT_import_include,
    GNS_PT_import_transform,
    GNS_PT_import_geometry,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
