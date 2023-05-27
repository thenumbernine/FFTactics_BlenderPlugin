# https://ffhacktics.com/wiki/Maps/Mesh
# https://ffhacktics.com/wiki/Maps/GNS

import math
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

# overload the gns classes to do blender stuff

class BlenderTexBlob(gns.TexBlob):
    def __init__(self, record, filename, mapdir):
        super().__init__(record, filename, mapdir)

        # here's the indexed texture, though it's not attached to anything
        self.indexImg = bpy.data.images.new(self.filename + ' Tex Indexed', width=self.width, height=self.height)
        self.indexImg.alpha_mode = 'NONE'
        self.indexImg.colorspace_settings.name = 'Raw'
        self.indexImg.pixels = [
            ch
            for colorIndex in self.pixels
            for ch in (
                (colorIndex+.5)/16.,
                (colorIndex+.5)/16.,
                (colorIndex+.5)/16.,
                1.
            )
        ]

    def writeTexture(self, filepath):
        pixRGBA = self.indexImg.pixels
        data = b''
        for y in range(self.height):
            for x in range(self.rowsize):
                data += bytes(TwoNibbles(
                    int(16. * pixRGBA[0 + 4 * (0 + 2 * (x + self.rowsize * y))]),
                    int(16. * pixRGBA[0 + 4 * (1 + 2 * (x + self.rowsize * y))])
                ))
        file = open(filepath, 'wb')
        file.write(data)
        file.close()

class BlenderPalChunk(gns.PalChunk):
    @staticmethod
    def palToImg(name, colors):
        img = bpy.data.images.new(name, width=len(colors), height=1)
        img.pixels = [
            ch
            for color in colors
            for ch in color.toTuple()
        ]
        return img

    def __init__(self, data, res):
        super().__init__(data, res)
        self.imgs = [
            self.palToImg(
                res.filename + ' ' + self.ident + ' Pal Tex ' + str(i),
                colors
            ) for (i, colors) in enumerate(self.pals)]

    @staticmethod
    def palImgToBytes(palImg):
        data = b''
        pixRGBA = palImg.pixels
        for i in range(len(pixRGBA)/4):
            data += bytes(RGBA5551.fromRGBA(
                pixRGBA[0 + 4 * i],
                pixRGBA[1 + 4 * i],
                pixRGBA[2 + 4 * i],
                pixRGBA[3 + 4 * i]
            ))
        return data

    def toBin(self):
        data = b''
        for img in self.imgs:
            data += self.palImgToBytes(img)
        return data

class BlenderColorPalChunk(BlenderPalChunk):
    ident = 'Color'

class BlenderGrayPalChunk(BlenderPalChunk):
    ident = 'Gray'

class BlenderLightChunk(gns.LightChunk):
    def __init__(self, data, res):
        super().__init__(data, res)

        center = (0,0,0)
        cornerPos = (0,0,0)
        if res.meshChunk != None:
            cornerPos = res.meshChunk.bbox[0]
            center = res.meshChunk.center

        # directional lights
        # https://stackoverflow.com/questions/17355617/can-you-add-a-light-source-in-blender-using-python
        self.dirLightObjs = []
        for i in range(3):
            lightName = res.filename + ' Light '+str(i)
            lightData = bpy.data.lights.new(name=lightName, type='SUN')
            lightData.energy = 20       # ?
            lightData.color = self.dirLightColors.ithToTuple(i)
            lightData.angle = math.pi
            lightObj = bpy.data.objects.new(name=lightName, object_data=lightData)
            # matrix_world rotate y- to z+ ...
            #lightObj.matrix_world = global_matrix
            # alright, how come with mesh, I can assign the matrix_world then assign the scale, and it rotates scales
            # but with this light, I apply matrix_world then I apply location, and the matrix_world is gone?
            # python is a languge without any block scope and with stupid indent rules.  it encourages polluting function namespaces.
            lightPos = (
                cornerPos[0] / 28 + i,
                cornerPos[2] / 24,
                -cornerPos[1] / 28
            )
            lightObj.location = lightPos[0], lightPos[1], lightPos[2]
            # calculate lightObj Euler angles by dirLightDirs
            # TODO figure out which rotates which...
            dir = self.dirLightDirs[i].toTuple()
            #print('light dir', dir)
            eulerAngles = (
                math.atan2(math.sqrt(dir[0]*dir[0] + dir[2]*dir[2]), dir[1]), # pitch
                math.atan2(dir[2], dir[0]),  # yaw
                0
               )
            lightObj.rotation_euler = eulerAngles[0], eulerAngles[1], eulerAngles[2]
            # hmm, this doesn't update like some random page said.
            #view_layer.update() # should transform the lightObj's (location, rotation_euler, scale) to its ... matrix?  matrix_locl? matrix_world? where int hee world is this documented?
            # setting matrix_world clears (location, rotation_euler, scale) ...
            # so does transforming it via '@'
            # even after calling view_layer.update()
            # best answer yet: https://blender.stackexchange.com/a/169424
            self.dirLightObjs.append(lightObj)


        # ambient light?  in blender?
        lightName = res.filename+' Ambient'
        lightData = bpy.data.lights.new(name=lightName, type='SUN')
        lightData.energy = 20       # ?
        lightData.color = self.ambientLightColor.toTuple()
        lightData.angle = math.pi
        lightObj = bpy.data.objects.new(name=lightName, object_data=lightData)
        #lightObj.matrix_world = global_matrix
        lightPos = (
            cornerPos[0] / 28 + 3,
            cornerPos[2] / 24,
            -cornerPos[1] / 28
        )
        lightObj.location = lightPos[0], lightPos[1], lightPos[2]
        self.ambLightObj = lightObj


        # setup bg mesh mat

        bgMat = bpy.data.materials.new(res.filename + ' Bg Mat')
        bgMat.use_backface_culling = True
        bgMatWrap = node_shader_utils.PrincipledBSDFWrapper(bgMat, is_readonly=False)
        bgMatWrap.use_nodes = True

        bsdf = bgMat.node_tree.nodes['Principled BSDF']
        bgMixNode = bgMat.node_tree.nodes.new('ShaderNodeMixRGB')
        bgMixNode.location = (-200, 0)
        bgMixNode.inputs[1].default_value[:3] = self.backgroundColors[0].toTuple()
        bgMixNode.inputs[2].default_value[:3] = self.backgroundColors[1].toTuple()
        bgMat.node_tree.links.new(bsdf.inputs['Base Color'], bgMixNode.outputs[0])

        bgMapRangeNode = bgMat.node_tree.nodes.new('ShaderNodeMapRange')
        bgMapRangeNode.location = (-400, 0)
        bgMapRangeNode.inputs['From Min'].default_value = 20.
        bgMapRangeNode.inputs['From Max'].default_value = -20.
        bgMapRangeNode.inputs['To Min'].default_value = 0.
        bgMapRangeNode.inputs['To Max'].default_value = 1.
        bgMat.node_tree.links.new(bgMixNode.inputs['Fac'], bgMapRangeNode.outputs[0])

        bgSepNode = bgMat.node_tree.nodes.new('ShaderNodeSeparateXYZ')
        bgSepNode.location = (-600, 0)
        bgMat.node_tree.links.new(bgMapRangeNode.inputs['Value'], bgSepNode.outputs['Z'])

        bgGeomNode = bgMat.node_tree.nodes.new('ShaderNodeNewGeometry')
        bgGeomNode.location = (-800, 0)
        bgMat.node_tree.links.new(bgSepNode.inputs['Vector'], bgGeomNode.outputs['Position'])


        # ... but the most common way of doing a skybox in blender is ...
        # ... overriding the world background
        # so ... what to do.
        # just put a big sphere around the outside?
        #  but how come when I do this, the sphere backface-culls, even when backface-culling is disabled?
        #  why does alpha not work when alpha-clipping or alpha-blending is enabled?
        #  and why did the goblin turn on the stove?
        # https://blender.stackexchange.com/questions/39409/how-can-i-make-the-outside-of-a-sphere-transparent
        #  or just make a background sphere ...
        # https://blender.stackexchange.com/questions/93298/create-a-uv-sphere-object-in-blender-from-python
        bgmesh = bpy.data.meshes.new(res.filename + ' Bg')
        bgmesh.materials.append(bgMat)
        bgmeshObj = bpy.data.objects.new(bgmesh.name, bgmesh)
        bgmeshObj.location = center[0]/28., center[1]/24., center[2]/28.
        bgmeshObj.scale = 20., 20., 20.

        # make the mesh a sphere
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=5)
        for f in bm.faces:
            # flip the normals so that, with backface culling, we will always see the sphere around the map and behind the map
            f.normal_flip()
            # set smooth shading
            f.smooth = True
        bm.normal_update()

        bm.to_mesh(bgmeshObj.data)
        bm.free()

        self.bgmeshObj = bgmeshObj

class BlenderTerrainChunk(gns.TerrainChunk):
    def __init__(self, data, res):
        super().__init__(data, res)

        ### create the terrain

        def makeTerrainObjForLayer(y):
            nonlocal res
            # vertexes of a [-.5, .5]^2 quad
            quadVtxs = [
                [-.5, -.5],
                [-.5, .5],
                [.5, .5],
                [.5, -.5]
            ]
            # from GaneshaDx ... seems like there should be some kind of bitfield per modified vertex ...
            liftPerVertPerSlopeType = [
                [0x25, 0x58, 0x14, 0x66, 0x69, 0x99],
                [0x85, 0x58, 0x44, 0x96, 0x69, 0x99],
                [0x85, 0x52, 0x41, 0x96, 0x66, 0x99],
                [0x52, 0x25, 0x11, 0x96, 0x66, 0x69],
            ]

            vtxs = []
            faces = []
            tilesFlattened = []
            for z in range(self.terrainSize[1]):
                for x in range(self.terrainSize[0]):
                    tile = self.terrainTiles[y][z][x]
                    vi = len(vtxs)
                    faces.append([vi+0, vi+1, vi+2, vi+3])
                    for (i, q) in enumerate(quadVtxs):
                        vtxs.append((
                            x + .5 + q[0],
                            -.5 * (tile.halfHeight + (tile.slopeHeight if tile.slopeType in liftPerVertPerSlopeType[i] else 0)),
                            z + .5 + q[1]
                        ))
                    tilesFlattened.append(tile)
            mesh = bpy.data.meshes.new(res.filename + ' Terrain'+str(y))
            mesh.materials.append(res.gns.terrainMat)
            mesh.from_pydata(vtxs, [], faces)
            terrainMeshObj = bpy.data.objects.new(mesh.name, mesh)
            terrainMeshObj.hide_render = True

            tagNames = [
                'surfaceType',
                'depth',
                'cantCursor',
                'cantWalk',
                'rotFlags',
                'unk0_6',
                'unk1',
                'unk5',
                'unk6_2'
                # TODO visAngles
                # via terrain mesh
                #'halfHeight',
                #'slopeHeight',
                #'slopeType',
            ]

            # custom per-face attributes for the terrain:
            # doI have to do this once at all, or once per mesh?
            # https://blender.stackexchange.com/questions/4964/setting-additional-properties-per-face
            import bmesh
            bm = bmesh.new()
            if bpy.context.mode == 'EDIT_MESH':
                bm.from_edit_mesh(terrainMeshObj.data)
            else:
                bm.from_mesh(terrainMeshObj.data)
            tags = {}
            for name in tagNames:
                tags[name] = bm.faces.layers.int.new(name)
                tags[name] = bm.faces.layers.int.get(name)
            # example says to write to bm.edges[faceNo] to change a face property ... ?
            # but they read from bm.faces[faceNo] ... wtf?
            # ... BMElemSeq[index]: outdated internal index table, run ensure_lookup_table() first
            bm.faces.ensure_lookup_table()
            for (i, tile) in enumerate(tilesFlattened):
                for name in tagNames:
                    bm.faces[i][tags[name]] = getattr(tile, name)
            if bpy.context.mode == 'EDIT_MESH':
                bm.updated_edit_mesh(terrainMeshObj.data)
            else:
                bm.to_mesh(terrainMeshObj.data)
            bm.free()

            return terrainMeshObj

        self.terrainMeshObjs = []
        for y in range(2):
            self.terrainMeshObjs.append(makeTerrainObjForLayer(y))


class BlenderNonTexBlob(gns.NonTexBlob):
    chunkIOClasses = {
        gns.CHUNK_MESH : gns.MeshChunk,
        gns.CHUNK_COLORPALS : BlenderColorPalChunk,
        gns.CHUNK_LIGHTS : BlenderLightChunk,
        gns.CHUNK_TERRAIN : BlenderTerrainChunk,
        gns.CHUNK_TEX_ANIM : gns.TexAnimChunk,
        #gns.CHUNK_PAL_ANIM : gns.PalAnimChunk,
        gns.CHUNK_GRAYPALS : BlenderGrayPalChunk,
        gns.CHUNK_VISANGLES : gns.VisAngleChunk,
    }

# this class has become a GNS wrapper + collection of all mapstates
class BlenderGNS(gns.GNS):
    TexBlob = BlenderTexBlob
    NonTexBlob = BlenderNonTexBlob
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
        self.loadCommon()
        
        super().__init__(filepath)
        
        if len(self.allMapStates) == 0:
            raise Exception("sorry there's no map states for this map...")

        progress.enter_substeps(3, "Parsing GNS file...")

        self.collections = []
        for (i, mapState) in enumerate(self.allMapStates):
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
        super().setMapState(mapState)

        # copy texture resource fields

        self.indexImg = None
        if len(self.texRess) > 0:
            self.indexImg = self.texRess[-1].indexImg
            # what happens if we have more than one
            if len(self.texRess) > 2:   # >2 since i'm adding tex 0 always
                print("hmm, we got "+str(len(self.texRess))+" textures...")


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
                        (v.texcoord.x + .5) / self.TexBlob.width,
                        (256 * s.texFace.page + v.texcoord.y + .5) / self.TexBlob.height
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
        if False:
            mapdir = os.path.dirname(filepath)
            for i in range(126):
                fn = os.path.join(mapdir, f'MAP{i:03d}.GNS')
                print('Loading', fn)
                try:
                    gns.GNS(fn)
                except Exception as e:
                    print("failed with error", e)
            print("DONE")
            raise Exception("done")

        # set world color
        world = bpy.data.worlds['World']
        background = world.node_tree.nodes['Background']
        background.inputs[0].default_value = (1, 1, 1, 1)
        background.inputs[1].default_value = 1

        # load gns file
        m = BlenderGNS(
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
