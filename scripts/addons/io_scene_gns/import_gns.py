# https://ffhacktics.com/wiki/Maps/Mesh
# https://ffhacktics.com/wiki/Maps/GNS

import array
import os
import os.path
import sys
import time
import bpy
import mathutils
from ctypes import *
from datetime import datetime

from bpy_extras.io_utils import unpack_list
from bpy_extras.image_utils import load_image
from bpy_extras.wm_utils.progress_report import ProgressReport
from bpy_extras import node_shader_utils

from . import gns

################################ fft/map/__init__.py ################################


class Map(object):
    def __init__(self,
        filepath,
        progress,
        context,
        global_scale_x,
        global_scale_y,
        global_scale_z,
        global_matrix
    ):
        progress.enter_substeps(1, "Importing GNS %r..." % filepath)

        self.filepath = filepath
        self.mapdir = os.path.dirname(filepath)
        self.filename = os.path.basename(filepath)
        self.nameroot = os.path.splitext(self.filename)[0]

        self.loadCommon()

        self.readGNS()

        progress.enter_substeps(3, "Parsing GNS file...")

        # bail out if we're just reading headers and not building scenes
        # TODO separate the GNS reading from the Blender building?
        if context == None:
            return

        self.collections = []
        for (i, mapState) in enumerate(self.gns.allMapStates):
            self.setMapState(mapState)
            mapConfigIndex, dayNight, weather = mapState
            collectionName = (self.nameroot
                + ' cfg=' + str(mapConfigIndex)
                + ' ' + ('night' if dayNight else 'day')
                + ' weather=' + str(weather)
            )
            collection = self.buildCollection(
                context,
                progress,
                collectionName,
                global_scale_x,
                global_scale_y,
                global_scale_z,
                global_matrix)
            #if i > 0:
                # when I set 'hide_viewport' here, un-clicking it in the scene collection panel doesn't reveal it ...
                #collection.hide_viewport = True
                # AttributeError: 'Collection' object has no attribute 'exclude'
                #collection.exclude = True
                # but reading this makes it sound like you can't do this until all collections are settled
                # https://blenderartists.org/t/show-hide-collection-blender-beta-2-80/1141768
            self.collections.append(collection)

        progress.leave_substeps("Done.")
        progress.leave_substeps("Finished importing: %r" % filepath)


    def readGNS(self):
        self.gns = gns.GNS(self.filepath)

        if len(self.gns.allMapStates) == 0:
            raise Exception("sorry there's no map states for this map...")

        # now, here, per resource file, load *everything* you can
        # I'm gonna put everything inside blender first and then sort it out per-scene later

        self.allTexRes = []
        self.allMeshRes = []
        for (i, r) in enumerate(self.gns.allRecords):
            print('record', self.gns.filenameForSector[r.sector], str(r), end='')
            if r.resourceType == r.RESOURCE_TEXTURE:
                print('...tex')
                self.allTexRes.append(gns.TexBlob(
                    r,
                    self.gns.filenameForSector[r.sector],
                    self.mapdir
                ))
            elif (r.resourceType == r.RESOURCE_MESH_INIT
                or r.resourceType == r.RESOURCE_MESH_REPL
                or r.resourceType == r.RESOURCE_MESH_ALT):
                res = gns.NonTexBlob(
                    r,
                    self.gns.filenameForSector[r.sector],
                    self.mapdir,
                    self
                )
                print('...res w/chunks '+str([i for i, e in enumerate(res.header) if e != 0]))
                self.allMeshRes.append(res)
            # else keep it anywhere?



    # create blender nodes used by everything
    def loadCommon(self):
        # create the terrain material
        # TODO this can be shared with everything

        terrainMat = bpy.data.materials.new('Terrain Mat')
        terrainMatWrap = node_shader_utils.PrincipledBSDFWrapper(terrainMat, is_readonly=False)
        terrainMatWrap.ior = 1
        terrainMatWrap.alpha = .5
        terrainMatWrap.use_nodes = True
        terrainMat.blend_method = 'BLEND'

        bsdf = terrainMat.node_tree.nodes['Principled BSDF']
        brickTexNode = terrainMat.node_tree.nodes.new('ShaderNodeTexBrick')
        brickTexNode.location = (-200, 0)
        brickTexNode.offset = 0
        brickTexNode.offset_frequency = 1
        brickTexNode.squash = 1
        brickTexNode.squash_frequency = 1
        brickTexNode.inputs['Color1'].default_value = (1,1,1,0)
        brickTexNode.inputs['Color2'].default_value = (0,0,0,0)
        brickTexNode.inputs['Mortar'].default_value = (0,0,1,1)
        brickTexNode.inputs['Scale'].default_value = 1
        brickTexNode.inputs['Mortar Size'].default_value = .1
        brickTexNode.inputs['Mortar Smooth'].default_value = 1
        brickTexNode.inputs['Bias'].default_value = 1
        brickTexNode.inputs['Brick Width'].default_value = 1
        brickTexNode.inputs['Row Height'].default_value = 1
        terrainMat.node_tree.links.new(bsdf.inputs['Base Color'], brickTexNode.outputs['Color'])

        terrainGeomNode = terrainMat.node_tree.nodes.new('ShaderNodeNewGeometry')
        terrainGeomNode.location = (-400, 0)
        terrainMat.node_tree.links.new(brickTexNode.inputs['Vector'], terrainGeomNode.outputs['Position'])

        self.terrainMat = terrainMat

    def setMapState(self, mapState):
        """
        what if there's more than 1 texture?
        map000 has no textures
        map051 and map105 have two textures (how are those extra textures referenced in the map file? tex face page?)
        map099, 116, 117, 118, 119, 120 can't find the mesh chunk?
        #assert len(self.textureFilenames) == 1

        ex map001
        has 19 dif tex (0x17)
        has 1 mesh_init (0x2e)
        has 1 mesh_repl (0x2f)
        has 19 dif mesh_alt (0x30)
        has 1 eof (0x31)

        ex map002
        has 20 dif texture (0x17) resources?
        has 1 dif mesh_repl (0x2f)
        has 19 dif mesh_alt (0x30)
        has 1 eof (0x31)
        """

        mapConfigIndex, dayNight, weather = mapState
        #print("setting config", mapConfigIndex, dayNight, weather)
        # now pick one ...
        # or somehow let the user decide which one to pick?
        #mapState = (mapConfigIndex, dayNight, weather)
        #mapState = self.gns.allMapStates[0]
        #mapState = self.gns.allMapStates[1]
        #mapState = (1,1,4)
        # are all configurations defined for all maps?
        # TODO

        # now set the map state to its default: arrangement==0, weather==0 night==0
        # what about maps that don't have this particular state?
        # how about instead, sort all states, and pick the one closest to this ...
        self.nonTexRess = list(filter(
            lambda r: r.record.getMapState() == mapState
                # ... right?  I also want the init mesh in here, right?
                or r.record.resourceType == r.record.RESOURCE_MESH_INIT,
            self.allMeshRes))
        self.texRess = []
        for i, r in enumerate(self.allTexRes):
            # always keep the first one?  and pick the last one? same as init mesh?  not sure
            # but map001 arrangement=1 day weather=0 is missing a texture ...
            if r.record.getMapState() == mapState or i == 0:
                self.texRess.append(r)

        # ... what order does the records() chunks[] system work?
        #self.nonTexRess.reverse()

        # map from mesh and texture record to mesh filename
        getPathForRes = lambda r: r.filename
        #print('nonTextureFilenames', list(map(getPathForRes, self.nonTexRess)))
        #print('textureFilenames', list(map(getPathForRes, self.texRess)))


        # update fields ...
        # ... tho maybe do this another way ...
        # TODO instead of setFields / getattr, how about a 'getField' method that does the same?

        # copy texture resource fields

        self.indexImg = None
        if len(self.texRess) > 0:
            self.indexImg = self.texRess[-1].indexImg
            # what happens if we have more than one
            if len(self.texRess) > 2:   # >2 since i'm adding tex 0 always
                print("hmm, we got "+str(len(self.texRess))+" textures...")

        # copy mesh resource fields

        def setResField(field):
            for res in self.nonTexRess:
                if hasattr(res, field):
                    value = getattr(res, field)
                    # TODO should I ever have None be valid?
                    if value != None:
                        setattr(self, field, value)
                        return
        for field in [
            'meshChunk',
            'colorPalChunk',
            'grayPalChunk',
            'lightChunk',
            'terrainChunk'
        ]:
            setResField(field)

    # build a collection per-map-state.
    # return it and map stores it in .collections
    # minimize the # of blender objects created in this -- try to push as many to the chunk creation as possible (to reduce duplication)
    def buildCollection(self,
        context,
        progress,
        collectionName,
        global_scale_x,
        global_scale_y,
        global_scale_z,
        global_matrix
    ):
        newObjects = []  # put new objects here

        view_layer = context.view_layer
        #collection = view_layer.active_layer_collection.collection
        collection = bpy.data.collections.new(collectionName)
        bpy.context.scene.collection.children.link(collection)

        ### make the material for textured faces

        uniqueMaterials = {}

        matPerPal = None
        if self.indexImg != None:
            # Write out the indexed image with each 16 palettes applied to it
            # This can only be done once the texture and color-palette NonTexBlob have been read in
            # But once we have the texture, it's pretty much 1:1 with the color-palette
            matPerPal = [None] * len(self.colorPalChunk.imgs)
            for (i, pal) in enumerate(self.colorPalChunk.imgs):
                # get image ...
                # https://blender.stackexchange.com/questions/643/is-it-possible-to-create-image-data-and-save-to-a-file-from-a-script
                mat = bpy.data.materials.new(self.nameroot + ' Mat Tex w Pal '+str(i))
                uniqueMaterials[mat.name] = mat
                matPerPal[i] = mat
                matWrap = node_shader_utils.PrincipledBSDFWrapper(mat, is_readonly=False)
                matWrap.use_nodes = True

                # https://blender.stackexchange.com/questions/157531/blender-2-8-python-add-texture-image
                palNode = mat.node_tree.nodes.new('ShaderNodeTexImage')
                palNode.image = pal
                palNode.interpolation = 'Closest'
                palNode.location = (-300, 0)

                indexNode = mat.node_tree.nodes.new('ShaderNodeTexImage')
                indexNode.image = self.indexImg
                indexNode.interpolation = 'Closest'
                indexNode.location = (-600, 0)

                bsdf = mat.node_tree.nodes['Principled BSDF']
                mat.node_tree.links.new(bsdf.inputs['Base Color'], palNode.outputs['Color'])
                mat.node_tree.links.new(bsdf.inputs['Alpha'], palNode.outputs['Alpha'])
                mat.node_tree.links.new(palNode.inputs['Vector'], indexNode.outputs['Color'])

                # setup transparency
                # link texture alpha channel to Principled BSDF material
                # https://blender.stackexchange.com/a/239948
                matWrap.ior = 1.
                matWrap.alpha = 1.
                #mat.blend_method = 'BLEND'  #the .obj loader has BLEND, but it makes everything semitransparent to the background grid
                mat.blend_method = 'CLIP'    # ... and so far neither BLEND nor CLIP makes the tree transparent

                # default specular is 1, which is shiny, which is ugly
                matWrap.specular = 0.
                matWrap.specular_tint = 0.
                matWrap.roughness = 0.


        ### make the material for untextured faces

        matWOTex = bpy.data.materials.new(self.nameroot + ' Mat Untex')
        uniqueMaterials[matWOTex.name] = matWOTex
        matWOTexWrap = node_shader_utils.PrincipledBSDFWrapper(matWOTex, is_readonly=False)
        matWOTexWrap.use_nodes = True
        matWOTexWrap.specular = 0
        matWOTexWrap.base_color = (0., 0., 0.)


        ### make the mesh
        # can I make this in the Resource and not here?
        # no?  because mesh has faces, faces have materials, materials depend on tex, tex varies per-state ...

        material_mapping = {name: i for i, name in enumerate(uniqueMaterials)}
        materials = [None] * len(uniqueMaterials)
        for name, index in material_mapping.items():
            materials[index] = uniqueMaterials[name]

        mesh = bpy.data.meshes.new(self.nameroot + ' Mesh')
        for material in materials:
            mesh.materials.append(material)

        # flip face order
        # I guess I could just set the cw vs ccw ...
        # also handle FFT tristrip => Blender quads
        def vertexesForPoly(poly):
            if len(poly.vtxs) == 4:
                return [poly.vtxs[2], poly.vtxs[3], poly.vtxs[1], poly.vtxs[0]]  # cw => ccw and tristrip -> quad
            return [poly.vtxs[2], poly.vtxs[1], poly.vtxs[0]]                    # cw front-face => ccw front-face

        # TODO try with this
        # https://blender.stackexchange.com/q/53709
        meshVtxPos = []
        meshVtxNormals = []
        meshVtxTCs = []
        tot_loops = 0
        faces = []  # tuples of the faces
        vi = 0
        vti = 0
        for s in self.polygons():
            # if we didn't get a texture then we're not applying textures
            # otherwise only apply to TriTex and QuadTex
            isTexd = matPerPal != None and s.isTex
            vs = vertexesForPoly(s)
            n = len(vs)
            for v in vs:
                meshVtxPos.append(v.pos.toTuple())

                if isTexd:
                    meshVtxTCs.append((
                        (v.texcoord.x + .5) / gns.TexBlob.width,
                        (256 * s.texFace.page + v.texcoord.y + .5) / gns.TexBlob.height
                    ))
                    meshVtxNormals.append(v.normal.toTuple())
                else:
                    meshVtxTCs.append((0,0))
                    meshVtxNormals.append((0,0,0))

            face_vert_loc_indices = [vi+j for j in range(n)]
            face_vert_nor_indices = [vti+j for j in range(n)]
            face_vert_tex_indices = [vti+j for j in range(n)]
            faces.append((
                face_vert_loc_indices,
                face_vert_nor_indices,
                face_vert_tex_indices,
                matPerPal[s.texFace.pal].name if isTexd else matWOTex.name
            ))
            tot_loops += n

            vi+=n
            #if isTexd:
            vti+=n


        mesh.polygons.add(len(faces))
        mesh.loops.add(tot_loops)
        mesh.vertices.add(len(meshVtxPos))

        mesh.vertices.foreach_set("co", unpack_list(meshVtxPos))

        faces_loop_start = []
        lidx = 0
        for f in faces:
            face_vert_loc_indices = f[0]
            nbr_vidx = len(face_vert_loc_indices)
            faces_loop_start.append(lidx)
            lidx += nbr_vidx
        faces_loop_total = tuple(len(face_vert_loc_indices) for (face_vert_loc_indices, _, _, _) in faces)

        loops_vert_idx = tuple(vidx for (face_vert_loc_indices, _, _, _) in faces for vidx in face_vert_loc_indices)
        mesh.loops.foreach_set("vertex_index", loops_vert_idx)
        mesh.polygons.foreach_set("loop_start", faces_loop_start)
        mesh.polygons.foreach_set("loop_total", faces_loop_total)

        faces_ma_index = tuple(material_mapping[context_material] for (_, _, _, context_material) in faces)
        mesh.polygons.foreach_set("material_index", faces_ma_index)

        mesh.polygons.foreach_set("use_smooth", [False] * len(faces))

        if meshVtxNormals and mesh.loops:
            mesh.create_normals_split()
            mesh.loops.foreach_set(
                "normal",
                tuple(no for (_, face_vert_nor_indices, _, _) in faces
                                 for face_noidx in face_vert_nor_indices
                                 for no in meshVtxNormals[face_noidx])
            )

        if meshVtxTCs and mesh.polygons:
            mesh.uv_layers.new(do_init=False)
            loops_uv = tuple(uv for (_, _, face_vert_tex_indices, _) in faces
                                for face_uvidx in face_vert_tex_indices
                                for uv in meshVtxTCs[face_uvidx])
            mesh.uv_layers[0].data.foreach_set("uv", loops_uv)

        mesh.validate(clean_customdata=False)  # *Very* important to not remove lnors here!
        mesh.update()

        if meshVtxNormals:
            clnors = array.array('f', [0.0] * (len(mesh.loops) * 3))
            mesh.loops.foreach_get("normal", clnors)
            mesh.polygons.foreach_set("use_smooth", [False] * len(mesh.polygons))
            mesh.normals_split_custom_set(tuple(zip(*(iter(clnors),) * 3)))
            # use_auto_smooth = True looks too dark ... thanks to all those zero normals I'm betting?
            mesh.use_auto_smooth = False

        meshObj = bpy.data.objects.new(mesh.name, mesh)
        meshObj.matrix_world = global_matrix
        meshObj.scale = 1./28., 1./24., 1./28.
        newObjects.append(meshObj)

        if hasattr(self, 'terrainChunk'):
            for terrainMeshObj in self.terrainChunk.terrainMeshObjs:
                terrainMeshObj.matrix_world = global_matrix
                # once again, is this applied before or after matrix_world? before or after view_later.update() ?
                # looks like it is in blender coordinates, i.e. z-up
                terrainMeshObj.location = 0, 0, .01
                newObjects.append(terrainMeshObj)

        if hasattr(self, 'lightChunk'):
            for obj in self.lightChunk.dirLightObjs:
                obj.matrix_world = global_matrix
                newObjects.append(obj)
            newObjects.append(self.lightChunk.ambLightObj)
            self.lightChunk.ambLightObj.matrix_world = global_matrix
            newObjects.append(self.lightChunk.bgmeshObj)

        # flip normals ... ?
        #bpy.ops.object.editmode_toggle()
        #bpy.ops.mesh.select_all(action='SELECT')
        #bpy.ops.mesh.flip_normals()
        #bpy.ops.object.mode_set()
        # view_layer.objects.active = bgmeshObj

        ### Create new objects
        # TODO this once at a time?
        for obj in newObjects:
            collection.objects.link(obj)
            obj.select_set(True)

        # has to be set after ... bleh ...
        #if hasattr(self, 'bgmeshObj'):
            # how come this works if I add the bgmeshObj earlier?
            # RuntimeError: Operator bpy.ops.object.modifier_add.poll() Context missing active object
            #self.bgmeshObj.select_set(True)
            #bpy.ops.object.modifier_add(type='SUBSURF')
            #bpy.ops.object.shade_smooth()

        view_layer.update()

        return collection

    def polygons(self):
        return (self.meshChunk.triTexs
            + self.meshChunk.quadTexs
            + self.meshChunk.triUntexs
            + self.meshChunk.quadUntexs)

################################ import_gns ################################

def load(context,
         filepath,
         *,
         relpath=None,
         global_scale_x=28.0,
         global_scale_y=24.0,
         global_scale_z=28.0,
         global_matrix=None,
         ):
    with ProgressReport(context.window_manager) as progress:

        if global_matrix is None:
            global_matrix = mathutils.Matrix()

        # deselect all
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        # hack for testing
        """
        if True:
            mapdir = os.path.dirname(filepath)
            for i in range(1,126):
                fn = os.path.join(mapdir, f'MAP{i:03d}.GNS')
                print('Loading', fn)
                Map(fn, progress, None, None, None, None, None)
            print("DONE")
            raise "raise"
        """

        # set world color
        world = bpy.data.worlds['World']
        background = world.node_tree.nodes['Background']
        background.inputs[0].default_value = (1, 1, 1, 1)
        background.inputs[1].default_value = 1

        # load map
        m = Map(
            filepath,
            progress,
            context,
            global_scale_x,
            global_scale_y,
            global_scale_z,
            global_matrix)


        # why is everything in blender api so ridiculously difficult to do...
        # https://blenderartists.org/t/show-hide-collection-blender-beta-2-80/1141768
        def get_viewport_ordered_collections(context):
            def fn(c, out, addme):
                if addme:
                    out.append(c)
                for c1 in c.children:
                    out.append(c1)
                for c1 in c.children:
                    fn(c1, out, False)
            collections = []
            fn(context.scene.collection, collections, True)
            return collections

        def get_area_from_context(context, area_type):
            area = None
            for a in context.screen.areas:
                if a.type == area_type:
                    area = a
                    break
            return area

        def set_collection_viewport_visibility(context, targetCollection, visibility=True):
            collections = get_viewport_ordered_collections(context)
            collection = None
            index = 0
            for c in collections:
                if c == targetCollection:
                    collection = c
                    break
                index += 1
            if collection is None:
                return
            first_object = None
            if len(collection.objects) > 0:
                first_object = collection.objects[0]
            try:
                bpy.ops.object.hide_collection(context, collection_index=index, toggle=True)
                if first_object.visible_get() != visibility:
                    bpy.ops.object.hide_collection(context, collection_index=index, toggle=True)
            except:
                context_override = context.copy()
                context_override['area'] = get_area_from_context(context, 'VIEW_3D')
                bpy.ops.object.hide_collection(context_override, collection_index=index, toggle=True)
                if first_object.visible_get() != visibility:
                    bpy.ops.object.hide_collection(context_override, collection_index=index, toggle=True)

        for i in range(1,len(m.collections)):
            set_collection_viewport_visibility(context, m.collections[i], visibility=False)
        set_collection_viewport_visibility(context, m.collections[0], visibility=True)

        # ... and those 50 lines of code are what is needed to just hide an object in the viewport

    return {'FINISHED'}
