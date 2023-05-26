# https://ffhacktics.com/wiki/Maps/Mesh

import array
import os
import os.path
import sys
import time
import bpy
import math
import mathutils
from ctypes import *
from datetime import datetime

from bpy_extras.io_utils import unpack_list
from bpy_extras.image_utils import load_image
from bpy_extras.wm_utils.progress_report import ProgressReport
from bpy_extras import node_shader_utils

class FFTStruct(LittleEndianStructure):
    _pack_ = 1
    # why isn't there an easy way to do this?
    def toTuple(self):
        return tuple(getattr(self, x[0]) for x in self._fields_)

    def __str__(self):
        return '{'+', '.join(x[0]+'='+str(getattr(self, x[0])) for x in self._fields_)+'}'

# list of these in the GNS file that direct us to other resources
# what to call it? resource? resource header?
class GNSRecord(FFTStruct):
    _fields_ = [
        # GaneshaDx looks at only the low byte here,
        # and says only 0x22, 0x30, and 0x70 are acceptable
        ('sig', c_uint16),

        # 0 = primary
        # 1 = secondary
        # from the consts in here I'd say there's up to ==5 ?
        # 'arrangement' eh?  'config' ?
        ('arrangement', c_uint8),

        # for map002 it's always 0
        ('unknown3', c_uint8, 4),

        # how bright<->dark is the map
        # 0 = brightest
        # 4 = darkest
        # 0..4 by the enums in python Ganesha
        # from 'none' to 'strong'
        ('weather', c_uint8, 3),

        # 0 = day
        # 1 = night
        ('isNight', c_uint8, 1),

        # always 1?
        ('resourceFlag', c_uint8),

        # 0x17 = texture
        # 0x2e = initial mesh
        # 0x2f = replacement mesh
        # 0x30 = alternative mesh
        # 0x31 = EOF (and the struct might be truncated)
        # 0x80 0x85 0x86 0x87 0x88 = also listed in GaneshaDx
        ('resourceType', c_uint8),

        # trails GNSRecord if it isn't a RESOURCE_EOF
        # do I really need to break these into two separate reads?
        # I think GaneshaDx puts a threshold of 20 bytes ... meaning we shoudl always be able to access both structs...

        # for map002 it's always 0x3333
        ('unknown6', c_uint16),

        # disk sector
        ('sector', c_uint32),

        # file size, rounded up to 2k block
        # sector plus roundup(size/2k) = next sector
        # but is there a relation between the file ext no? both are sequential in same order.  neither are 1:1 with indexes
        ('size', c_uint32),

        # for map002 always 0x88776655
        ('unknownA', c_uint32),
    ]

    # return the tuple of arrangement, isNight, weather which are used to uniquely identify ... bleh
    def getMapState(self):
        return (self.arrangement, self.isNight, self.weather)

assert sizeof(GNSRecord) == 20

class MeshHeader(FFTStruct):
    _fields_ = [
        ('numTriTex', c_uint16),
        ('numQuadTex', c_uint16),
        ('numTriUntex', c_uint16),
        ('numQuadUntex', c_uint16),
    ]

class VertexPos(FFTStruct):
    _fields_ = [
        ('x', c_int16),
        ('y', c_int16),
        ('z', c_int16),
    ]

class Normal(FFTStruct):
    _fields_ = [
        ('x', c_int16),
        ('y', c_int16),
        ('z', c_int16),
    ]

    def toTuple(self):
        return (
            self.x / 4096.,
            self.y / 4096.,
            self.z / 4096.,
        )

class TexCoord(FFTStruct):
    _fields_ = [
        ('x', c_uint8),
        ('y', c_uint8),
    ]
assert sizeof(TexCoord) == 2

# textured-triangle face information
class TriTexFace(FFTStruct):
    _fields_ = [
        ('uv0', TexCoord),
        ('pal', c_uint8, 4),
        ('unk2_4', c_uint8, 4),
        ('unk3', c_uint8),
        ('uv1', TexCoord),
        ('page', c_uint8, 2),
        ('unk6_2', c_uint8, 6),
        ('unk7', c_uint8),
        ('uv2', TexCoord),
    ]
assert sizeof(TriTexFace) == 10

# textured-quad face information
# matches TriTexFace but with uv3
class QuadTexFace(FFTStruct):
    _fields_ = [
        ('uv0', TexCoord),
        ('pal', c_uint8, 4),
        ('unk2_4', c_uint8, 4),
        ('unk3', c_uint8),
        ('uv1', TexCoord),
        ('page', c_uint8, 2),
        ('unk6_2', c_uint8, 6),
        ('unk7', c_uint8),
        ('uv2', TexCoord),
        ('uv3', TexCoord),
    ]
assert sizeof(QuadTexFace) == 12

# tile in-game position, stored per-textured-face
class TilePos(FFTStruct):
    _fields_ = [
        ('x', c_uint8),
        ('y', c_uint8, 1),
        ('z', c_uint8, 7),
    ]
assert sizeof(TilePos) == 2

def clamp(x,mn,mx):
    return max(mn, min(mx, x))

class RGBA5551(FFTStruct):
    _fields_ = [
        ('r', c_uint16, 5),
        ('g', c_uint16, 5),
        ('b', c_uint16, 5),
        ('a', c_uint16, 1)
    ]

    # TODO need some generic conversion method names?
    # deser / ser?  fromPy / toPy ?
    def toTuple(self):
        r = self.r / 31.
        g = self.g / 31.
        b = self.b / 31.
        a = float(self.a)
        if not (r == 0. and g == 0. and b == 0.):
            a = 1.
        return (r,g,b,a)

    @staticmethod
    def fromRGBA(r,g,b,a):
        if a < .5:
            return RGBA5551(0,0,0,0)
        else:
            return RGBA5551(
                31 * clamp(r, 0, 1),
                31 * clamp(g, 0, 1),
                31 * clamp(b, 0, 1),
                1)

# hmm can I inerit from c_uint16 and override some behavior or something?
#class LightColorChannel(FFTStruct):

class LightColors(FFTStruct):
    _fields_ = [
        ('r', c_uint16 * 3),
        ('g', c_uint16 * 3),
        ('b', c_uint16 * 3),
    ]

    # maybe an index operator?
    def ithToTuple(self, i):
        mask = (1<<11)-1
        return (
            (self.r[i] & mask) / float(mask),
            (self.g[i] & mask) / float(mask),
            (self.b[i] & mask) / float(mask)
        )

class RGB888(FFTStruct):
    _fields_ = [
        ('r', c_uint8),
        ('g', c_uint8),
        ('b', c_uint8),
    ]

    def toTuple(self):
        return (self.r / 255., self.g / 255., self.b / 255.)

'''
slope types:
0x00b = 00000000b Flat
0x52 = 01 01 00 10 b Incline E
0x58 = 01 01 10 00 b Incline W
0x25 = 00 10 01 01 b Incline S
0x85 = 10 00 01 01 b Incline N

0x41 = 01 00 00 01 b Convex NE
0x96 = 10 01 01 10 b Concave NE

0x11 = 00 01 00 01 b Convex SE
0x66 = 01 10 01 10 b Concave SE

0x14 = 00 01 01 00 b Convex SW
0x69 = 01 10 10 01 b Concave SW

0x44 = 01 00 01 00 b Convex NW
0x99 = 10 01 10 01 b Concave NW

hmmm .... there's gotta be some meaning to the bits wrt which vertex is raised, or the triangulation ...
4 bits needed for raised/lowered
and then 4 more ... only 1 needed for tesselation edge orientation

or maybe it's each vertex has 3 states?  cuz i'm seeing bit groupings by 4 sets of 2 bits, and none of the 2 bits are 11

'''
class TerrainTile(FFTStruct):
    _fields_ = [
        ('surfaceType', c_uint8, 6),
        ('unk0_6', c_uint8, 2),
        ('unk1', c_uint8),
        ('halfHeight', c_uint8),    # in half-tiles
        ('slopeHeight', c_uint8, 5),
        ('depth', c_uint8, 3),      # in half-tiles too?
        ('slopeType', c_uint8),
        ('unk5', c_uint8),
        ('cantCursor', c_uint8, 1),
        ('cantWalk', c_uint8, 1),
        ('unk6_2', c_uint8, 6),

        # bits vs rotation flags:
        # 0 = ne bottom
        # 1 = se bottom
        # 2 = sw bottom
        # 3 = nw bottom
        # 4 = ne top
        # 5 = se top
        # 6 = sw top
        # 7 = nw top
        ('rotFlags', c_uint8),
    ]
assert sizeof(TerrainTile) == 8

# can python ctypes do arrays-of-bitfields?
# ... can C structs? nope?
class TwoNibbles(FFTStruct):
    _fields_ = [
        ('lo', c_uint8, 4),
        ('hi', c_uint8, 4),
    ]
assert sizeof(TwoNibbles) == 1

class TexAnim(FFTStruct):
    _fields_ = [

        # 00:
        # 130 << 2 = 520
        # 520 - 2 * 256 = 8
        # so
        # 130 - 2 * 64 = 2 .. x4 to get texcoord = 8
        ('xOver4', c_uint8, 6),
        ('texPage', c_uint8, 2),

        # unknown, must be 3 maybe?  related to the rest of the bits of the texture page?
        # 3 for TexAnim, 0 (and y == 0x01e0) for PalAnim ?
        ('structSig', c_uint8),

        # 02:
        ('y', c_uint16),

        # 04:
        ('widthOver4', c_uint16),

        # 06:
        ('height', c_uint16),

        # 08:
        ('first_xOver4', c_uint8, 6),
        ('first_texPage', c_uint8, 2),
        ('first_mustBe3', c_uint8),

        # 0A:
        ('first_y', c_uint16),

        # 0C:
        ('unkC', c_uint16),

        # 0x01 = play forward, loop
        # 0x02 = play forward then reverse, loop
        # 0x05 = play forward upon UseFieldObject
        # 0x15 = play reverse upon UseFieldObject
        ('animType', c_uint8),

        ('numFrames', c_uint8),

        # 10:
        ('unk10', c_uint8),

        ('frameLenIn30Hz', c_uint8),

        # 12:
        ('unk12', c_uint16),
    ]
assert sizeof(TexAnim) == 0x14

# if TexAnim structSig == 0 && y == 0x01e0 then use this one:

class PalAnim(FFTStruct):
    _fields_ = [
        ('pal', c_uint8, 4),
        ('unk0_4', c_uint8, 4),
        ('structSig', c_uint8),  # must be 0
        ('unk2', c_uint16), # must be 0x1e0
        ('unk4', c_uint32),
        ('startIndex', c_uint8), # start index in anim data set
        ('unk9', c_uint8 * 5),
        ('unkE', c_uint8),  # must be 3
        ('numFrames', c_uint8),
        ('unk10', c_uint8),
        ('frameLenIn30Hz', c_uint8),
        ('unk12', c_uint16),
    ]
assert sizeof(PalAnim) == 0x14

################################ fft/map/gns.py ################################

# GaneshaDx: texture resources:
RESOURCE_TEXTURE = 0x17

# GaneshaDx: mesh resources:
# this is the init mesh, looks like it is always used unless overridden ...
RESOURCE_MESH_INIT = 0x2e # Always used with (0x22, 0, 0, 0). Always a big file.

# ... this is the override
# screenshot from ... ? shows RESOURCE_REPL with prim mesh, pal, lights, terrain, tex.anim., and pal.anim.
RESOURCE_MESH_REPL = 0x2f # Always used with (0x30, 0, 0, 0). Usually a big file.

# this is just pal and lights
RESOURCE_MESH_ALT = 0x30 # Used with many index combos. Usually a small file.

# GaneshaDx: other stuff I guess
RESOURCE_EOF = 0x31 # GaneshaDx calls this one "Padded" ... as in file-padding?  as in EOF record?
RESOURCE_UNKNOWN_EXTRA_DATA_A = 0x80 # from GaneshaDx
RESOURCE_UNKNOWN_TWIN_1 = 0x85
RESOURCE_UNKNOWN_TWIN_2 = 0x86
RESOURCE_UNKNOWN_TWIN_3 = 0x87
RESOURCE_UNKNOWN_TWIN_4 = 0x88

################################ fft/map/__init__.py ################################

class VertexTex(object):
    def __init__(self, pos, normal, texcoord):
        self.pos = pos
        self.normal = normal
        self.texcoord = texcoord

class TriTex(object):
    def __init__(self, points, normals, texFace, tilePos, visAngles):
        self.vtxs = [
            VertexTex(points[0], normals[0], texFace.uv0),
            VertexTex(points[1], normals[1], texFace.uv1),
            VertexTex(points[2], normals[2], texFace.uv2),
        ]
        self.texFace = texFace
        self.tilePos = tilePos
        self.visAngles = visAngles

class QuadTex(object):
    def __init__(self, points, normals, texFace, tilePos, visAngles):
        self.vtxs = [
            VertexTex(points[0], normals[0], texFace.uv0),
            VertexTex(points[1], normals[1], texFace.uv1),
            VertexTex(points[2], normals[2], texFace.uv2),
            VertexTex(points[3], normals[3], texFace.uv3),
        ]
        self.texFace = texFace
        self.tilePos = tilePos
        self.visAngles = visAngles


class VertexUntex(object):
    def __init__(self, pos):
        self.pos = pos

class TriUntex(object):
    def __init__(self, points, unknown, visAngles):
        self.vtxs = [
            VertexUntex(points[0]),
            VertexUntex(points[1]),
            VertexUntex(points[2]),
        ]
        self.unknown = unknown
        self.visAngles = visAngles

class QuadUntex(object):
    def __init__(self, points, unknown, visAngles):
        self.vtxs = [
            VertexUntex(points[0]),
            VertexUntex(points[1]),
            VertexUntex(points[2]),
            VertexUntex(points[3]),
        ]
        self.unknown = unknown
        self.visAngles = visAngles

class ResourceBlob(object):
    def __init__(self, record, filename, mapdir):
        self.record = record
        # extension-index:
        self.ext = int(os.path.splitext(filename)[1][1:])
        # after ctor, sort filenames then match with sectors, then write this.
        self.sector = None
        self.filename = filename
        self.filepath = os.path.join(mapdir, filename)

    # read whole file as one blob
    def readData(self):
        file = open(self.filepath, 'rb')
        data = file.read()
        file.close()
        return data

def countSectors(size):
    return (size >> 11) + (1 if size & ((1<<11)-1) else 0)

# colors are RGBA5551 array
def palToImg(name, colors):
    img = bpy.data.images.new(name, width=len(colors), height=1)
    img.pixels = [
        ch
        for color in colors
        for ch in color.toTuple()
    ]
    return img

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

class Chunk(object):
    def __init__(self, data):
        self.data = data
        self.ofs = 0

    # read bytes
    def readBytes(self, n=math.inf):
        if self.ofs + n > len(self.data):
            n = len(self.data) - self.ofs
        res = self.data[self.ofs:self.ofs+n]
        self.ofs += n
        return res

    # read a struct
    def read(self, cl):
        res = cl.from_buffer_copy(self.data[self.ofs:self.ofs+sizeof(cl)])
        self.ofs += sizeof(cl)
        return res

class VisAngleChunk(Chunk):
    # res isn't used.  just here for ctor consistency with other chunks.
    def __init__(self, data, res):
        super().__init__(data)
        # reading chunk 0x2c
        # from the 'writeVisAngles' function looks like this is written to a 1024 byte block always
        self.header = self.readBytes(0x380)
        self.triTexVisAngles = self.read(c_uint16 * 512)
        # ... and this is a 1536 byte block always
        self.quadTexVisAngles = self.read(c_uint16 * 768)
        self.triUntexVisAngles = self.read(c_uint16 * 64)
        self.quadUntexVisAngles = self.read(c_uint16 * 256)
        self.footer = self.readBytes()
        # does this mean we can only have 512 tex'd tris/tex'd quads/untex'd tris/untex'd quads?
        # GaneshaDx has these constants:
        #MaxTexturedTriangles = 360
        #MaxTexturedQuads = 710
        #MaxUntexturedTriangles = 64
        #MaxUntexturedQuads = 256
        # why are GaneshaDx's textured tri and quad counts lower than original python Ganesha's?
        # done reading chunk 0x2c

    # rather than crossing VisAngleChunk and MeshChunk,
    #  how about a 3rd party that holds both's info
    # (and the respective blender objects that go with it)
    # and then both can query it?
    # right now MeshChunk is taking responsibility for both.
    def toBin(self, meshChunk):
        triTexVisAngles = b''
        for polygon in meshChunk.triTexs:
            triTexVisAngles += bytes(polygon.visAngles)
        triTexVisAngles += b'\0' * (1024 - len(triTexVisAngles))

        quadTexVisAngles = b''
        for polygon in meshChunk.quadTexs:
            quadTexVisAngles += bytes(polygon.visAngles)
        quadTexVisAngles += b'\0' * (1536 - len(quadTexVisAngles))

        triUntexVisAngles = b''
        for polygon in meshChunk.triUntexs:
            triUntexVisAngles += bytes(polygon.visAngles)
        triUntexVisAngles += b'\0' * (128 - len(triUntexVisAngles))

        quadUntexVisAngles = b''
        for polygon in meshChunk.quadUntexs:
            quadUntexVisAngles += bytes(polygon.visAngles)
        quadUntexVisAngles += b'\0' * (512 - len(quadUntexVisAngles))

        return (
              self.header
            + triTexVisAngles
            + quadTexVisAngles
            + triUntexVisAngles
            + quadUntexVisAngles
            + self.footer
        )

# writing depends on the existence of the blender mesh
# and the blender mesh is going to have custom face attributes
# and only one of those custom face attributes is going to be the visangles
# so that means load the MeshChunk after visAngles (and all other chunks) are loaded
class MeshChunk(Chunk):
    # read the mesh chunk
    def __init__(self, data, res):
        super().__init__(data)

        if res.visAngleChunk == None:
            print("reading a mesh without visAngles ... expect an error in some corner case I forgot to accomodate for")

        # reading from chunk 0x10
        self.hdr = self.read(MeshHeader)
        self.triTexVtxs = self.read(VertexPos * (3 * self.hdr.numTriTex))
        self.quadTexVtxs = self.read(VertexPos * (4 * self.hdr.numQuadTex))
        self.triUntexVtxs = self.read(VertexPos * (3 * self.hdr.numTriUntex))
        self.quadUntexVtxs = self.read(VertexPos * (4 * self.hdr.numQuadUntex))
        self.triTexNormals = self.read(Normal * (3 * self.hdr.numTriTex))
        self.quadTexNormals = self.read(Normal * (4 * self.hdr.numQuadTex))
        self.triTexFaces = self.read(TriTexFace * self.hdr.numTriTex)
        self.quadTexFaces = self.read(QuadTexFace * self.hdr.numQuadTex)

        # all 1's for all except ...
        # map092.9 has a single quad unknown with a value of 0
        # map092.31 has a single quad unknown with value of 910344 / 0xde408
        # map099.7 has a single quad unknown with a value of 9240564  / 0x8cfff4
        # map117.7 has four quad unknowns with values:
        #  900244 / 0xdbc94
        #  3165114279 / 0xbca7cfa7
        #  2055616955 / 0x7a8639bb
        #  934824 / 0xe43a8
        self.triUntexUnknowns = self.read(c_uint32 * self.hdr.numTriUntex) # then comes unknown 4 bytes per untex-tri
        self.quadUntexUnknowns = self.read(c_uint32 * self.hdr.numQuadUntex) # then comes unknown 4 bytes per untex-quad
        #print('self.triUntexUnknowns', list(self.triUntexUnknowns))
        #print('self.quadUntexUnknowns', list(self.quadUntexUnknowns))

        self.triTexTilePos = self.read(TilePos * self.hdr.numTriTex) # then comes terrain info 2 bytes per tex-tri
        self.quadTexTilePos = self.read(TilePos * self.hdr.numQuadTex) # then comes terrain info 2 bytes per tex-quad
        # and that's it from chunk 0x10

        # now for aux calcs
        # this is based on 0x10 (mesh) and 0x2c (visAngles)
        # maybe cache here instead of inside MeshChunk if I was using visAngles ....
        # should I even store this / allow edits?
        # or should I try to auto calc it upon export?
        bboxMin = [math.inf] * 3
        bboxMax = [-math.inf] * 3
        for v in (list(self.triTexVtxs)
            + list(self.quadTexVtxs)
            + list(self.triUntexVtxs)
            + list(self.quadUntexVtxs)):
            v = v.toTuple()
            for i in range(3):
                bboxMin[i] = min(bboxMin[i], v[i])
                bboxMax[i] = max(bboxMax[i], v[i])
        self.bbox = (tuple(bboxMin), tuple(bboxMax))
        self.center = [None] * 3
        for i in range(3):
            self.center[i] = .5 * (self.bbox[0][i] + self.bbox[1][i])
        self.center = tuple(self.center)

        # still not sure if it's worth saving this in its own structure ...
        self.triTexs = []
        for i in range(self.hdr.numTriTex):
            self.triTexs.append(TriTex(
                self.triTexVtxs[3*i:3*(i+1)],
                self.triTexNormals[3*i:3*(i+1)],
                self.triTexFaces[i],
                self.triTexTilePos[i],
                res.visAngleChunk.triTexVisAngles[i] if res.visAngleChunk != None else None
            ))

        self.quadTexs = []
        for i in range(self.hdr.numQuadTex):
            self.quadTexs.append(QuadTex(
                self.quadTexVtxs[4*i:4*(i+1)],
                self.quadTexNormals[4*i:4*(i+1)],
                self.quadTexFaces[i],
                self.quadTexTilePos[i],
                res.visAngleChunk.quadTexVisAngles[i] if res.visAngleChunk != None else None
            ))

        self.triUntexs = []
        for i in range(self.hdr.numTriUntex):
            self.triUntexs.append(TriUntex(
                self.triUntexVtxs[3*i:3*(i+1)],
                self.triUntexUnknowns[i],
                res.visAngleChunk.triUntexVisAngles[i] if res.visAngleChunk != None else None
            ))

        self.quadUntexs = []
        for i in range(self.hdr.numQuadUntex):
            self.quadUntexs.append(QuadUntex(
                self.quadUntexVtxs[4*i:4*(i+1)],
                self.quadUntexUnknowns[i],
                res.visAngleChunk.quadUntexVisAngles[i] if res.visAngleChunk != None else None
            ))

    def toBin(self):
        # TODO recalc mesh based on blender mesh
        data = bytes(self.hdr)
        for polygon in self.polygons():
            for v in polygon.vtxs:
                data += bytes(v.pos)
        for polygon in self.triTexs + self.quadTexs:
            for v in polygon.vtxs:
                data += bytes(v.normal)
        for polygon in self.triTexs + self.quadTexs:
            if polygon.texFace.unk3 == 0:
                polygon.texFace.unk3 = 120
                polygon.texFace.unk6_2 = 3
            data += bytes(polygon.texFace)
        for polygon in self.triUntexs + self.quadUntexs:
            data += bytes(polygon.unknown)
        for polygon in self.triTexs + self.quadTexs:
            data += bytes(polygon.tilePos)
        return data

class PalChunk(Chunk):
    def __init__(self, data, res):
        super().__init__(data)
        # reading chunk
        self.imgs = [
            palToImg(
                res.filename + ' ' + self.ident + ' Pal Tex ' + str(i),
                self.read(RGBA5551 * 16)
            ) for i in range(16)]
        # done reading chunk

    def toBin(self):
        data = b''
        for img in self.imgs:
            data += palImgToBytes(img)
        return data

class ColorPalChunk(PalChunk): # 0x11
    ident = 'Color'

class GrayPalChunk(PalChunk):  # 0x1f
    ident = 'Gray'

class LightChunk(Chunk):
    def __init__(self, data, res):
        super().__init__(data)
        # reading chunk 0x19
        self.dirLightColors = self.read(LightColors)
        self.dirLightDirs = self.read(VertexPos * 3) # could be Normal structure as well, but both get normalized to the same value in the end
        self.ambientLightColor = self.read(RGB888)
        self.backgroundColors = self.read(RGB888 * 2)
        self.footer = self.readBytes()
        # done reading chunk 0x19

        cornerPos = (0,0,0)
        if res.meshChunk != None:
            cornerPos = res.meshChunk.bbox[0]

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
        # https://blender.stackexchange.com/questions/23884/creating-cycles-background-light-world-lighting-from-python
        # seems the most common way is ...
        # ... overriding the world background
        """
        world = bpy.data.worlds['World']
        background = world.node_tree.nodes['Background']
        background.inputs[0].default_value[:3] = self.ambientLightColor.toTuple()
        background.inputs[1].default_value = 5.
        """
        # but you can just do that once ... what if I want to load multiple map cfgs at a time?
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
        center = (0,0,0)
        if res.meshChunk != None:
            center = res.meshChunk.center
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

    def toBin(self):
        return (
              bytes(self.dirLightColors)
            + bytes(self.dirLightDirs)
            + bytes(self.ambientLightColors)
            + bytes(self.backgroundColors)
            + self.footer
        )

class TerrainChunk(Chunk):
    def __init__(self, data, res):
        super().__init__(data)
        # reading chunk 0x1a
        self.terrainSize = self.read(c_uint8 * 2)  # (sizeX, sizeZ)
        # weird, it leaves room for 256 total tiles for the first xz plane, and then the second is packed?
        terrainTileSrc = self.read(TerrainTile * (256 + self.terrainSize[0] * self.terrainSize[1]))
        self.footer = self.readBytes()
        # done reading chunk 0x1a

        # convert the terrainTiles from [z * terrainSize[0] + x] w/padding for y to [y][z][x]
        self.terrainTiles = []
        for y in range(2):
            level = []
            for z in range(self.terrainSize[1]):
                row = []
                for x in range(self.terrainSize[0]):
                    row.append(terrainTileSrc[256 * y + z * self.terrainSize[0] + x])
                level.append(row)
            self.terrainTiles.append(level)

        ### create the terrain

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

        tmesh = bpy.data.meshes.new(res.filename + ' Terrain')
        tmeshVtxs = []
        tmeshEdges = []
        tmeshFaces = []
        tilesFlattened = []
        for y in range(2):
            for z in range(self.terrainSize[1]):
                for x in range(self.terrainSize[0]):
                    tile = self.terrainTiles[y][z][x]
                    vi = len(tmeshVtxs)
                    tmeshFaces.append([vi+0, vi+1, vi+2, vi+3])
                    for (i, q) in enumerate(quadVtxs):
                        tmeshVtxs.append((
                            x + .5 + q[0],
                            -.5 * (tile.halfHeight + (tile.slopeHeight if tile.slopeType in liftPerVertPerSlopeType[i] else 0)),
                            z + .5 + q[1]
                        ))
                    tilesFlattened.append(tile)
        tmesh.from_pydata(tmeshVtxs, tmeshEdges, tmeshFaces)
        tmeshObj = bpy.data.objects.new(tmesh.name, tmesh)
        #tmeshObj.matrix_world = global_matrix
        tmeshObj.hide_render = True

        terrainMat = bpy.data.materials.new(res.filename + ' Terrain Mat')
        terrainMatWrap = node_shader_utils.PrincipledBSDFWrapper(terrainMat, is_readonly=False)
        terrainMatWrap.ior = 1
        terrainMatWrap.alpha = .2
        terrainMatWrap.use_nodes = True
        terrainMat.blend_method = 'BLEND'

        bsdf = terrainMat.node_tree.nodes['Principled BSDF']
        brickTexNode = terrainMat.node_tree.nodes.new('ShaderNodeTexBrick')
        brickTexNode.location = (-200, 0)
        brickTexNode.offset = 0
        brickTexNode.offset_frequency = 1
        brickTexNode.squash = 1
        brickTexNode.squash_frequency = 1
        brickTexNode.inputs[1].default_value = (1,1,1,0)    # Color1
        brickTexNode.inputs[2].default_value = (0,0,0,0)    # Color2
        brickTexNode.inputs[3].default_value = (0,0,1,1)    # Mortar
        brickTexNode.inputs[4].default_value = 1            # Scale
        brickTexNode.inputs[5].default_value = .1            # Mortar Size
        brickTexNode.inputs[6].default_value = 1            # Mortar Smoothness
        brickTexNode.inputs[7].default_value = 1            # Bias
        brickTexNode.inputs[8].default_value = 1            # Brick Width
        brickTexNode.inputs[9].default_value = 1            # Row Height
        terrainMat.node_tree.links.new(bsdf.inputs['Base Color'], brickTexNode.outputs[0])

        terrainGeomNode = terrainMat.node_tree.nodes.new('ShaderNodeNewGeometry')
        terrainGeomNode.location = (-400, 0)
        terrainMat.node_tree.links.new(brickTexNode.inputs['Vector'], terrainGeomNode.outputs['Position'])

        tmesh.materials.append(terrainMat)

        # custom per-face attributes for the terrain:
        # doI have to do this once at all, or once per mesh?
        # https://blender.stackexchange.com/questions/4964/setting-additional-properties-per-face
        import bmesh
        bm = bmesh.new()
        if bpy.context.mode == 'EDIT_MESH':
            bm.from_edit_mesh(tmeshObj.data)
        else:
            bm.from_mesh(tmeshObj.data)
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
            bm.updated_edit_mesh(tmeshObj.data)
        else:
            bm.to_mesh(tmeshObj.data)
        bm.free()

        self.tmeshObj = tmeshObj

    def toBin(self):
        # TODO read this back from the blender mesh
        assert len(self.terrainTiles) == 2
        self.terrainSize[0] = len(self.terrainTiles.tiles[0][0])
        self.terrainSize[1] = len(self.terrainTiles.tiles[0])
        data = bytes(self.terrainSize)
        for level in self.terrainTiles:
            for row in level:
                for tile in row:
                    data += bytes(tile)
            # Skip to second level of terrain data
            data += b'\0' * (sizeof(TerrainTile) * (256 - sizeX * sizeZ))
        data += self.footer
        return data

class TexAnimChunk(Chunk):
    def __init__(self, data, res):
        super().__init__(data)
        # begin reading 0x1b
        self.anims = self.read(TexAnim * 32)
        # done reading 0x1b

    def toBin(self):
        return bytes(self.anims)

class PalAnimChunk(Chunk):
    def __init__(self, data, res):
        super().__init__(data)
        # begin reading 0x1c
        self.pals = []
        for i in range(16):
            self.pals[i] =  self.read(RGBA5551 * 16)
        # done reading 0x1c

    def toBin(self):
        data = b''
        for pal in self.pals:
            data += bytes(pal)
        return data

class NonTexBlob(ResourceBlob):
    def __init__(self, record, filename, mapdir):
        super().__init__(record, filename, mapdir)
        data = self.readData()
        self.numSectors = countSectors(len(data))

        # chunks used in maps 001 thru 119:
        # in hex: 10, 11, 13, 19, 1a, 1b, 1c, 1f, 23, 24, 25, 26, 27, 28, 29, 2a, 2b, 2c
        # missing:
        # in hex: 12, 14, 15, 16, 17, 18, 1d, 1e, 20, 21, 22
        # ... seems like the first 64 bytes are used for something else
        numChunks = 49

        self.header = (c_uint32 * numChunks).from_buffer_copy(data)

        chunks = [None] * numChunks
        for i, entry in enumerate(self.header):
            begin = self.header[i]
            if begin:
                end = None
                for j in range(i + 1, numChunks):
                    if self.header[j]:
                        end = self.header[j]
                        break
                if end == None:
                    end = len(data)
                chunks[i] = data[begin:end]

        # needs to be read before meshChunk
        self.visAngleChunk = None
        if chunks[0x2c]:
            self.visAngleChunk = VisAngleChunk(chunks[0x2c], self)

        # needs to be read after visAngleChunk
        self.meshChunk = None
        if chunks[0x10]:
            self.meshChunk = MeshChunk(chunks[0x10], self)

        self.colorPalChunk = None
        if chunks[0x11]:
            self.colorPalChunk = ColorPalChunk(chunks[0x11], self)

        # 0x12 is unused
        # 0x13 is only nonzero for map000.5
        # 0x14..0x18 is unused

        # this needs bbox if it exists, which is calculated in meshChunk's ctor
        self.lightChunk = None
        if chunks[0x19]:
            self.lightChunk = LightChunk(chunks[0x19], self)

        self.terrainChunk = None
        if chunks[0x1a]:
            self.terrainChunk = TerrainChunk(chunks[0x1a], self)

        self.texAnimChunk = None
        if chunks[0x1b]:
            self.texAnimChunk = TexAnimChunk(chunks[0x1b], self)

        self.palAnimChunk = None
        # is this rgba palettes or is it another texAnim set?
        #if chunks[0x1c]:
        #    self.palAnimChunk = PalAnimChunk(chunks[0x1c], self)

        # 0x1d is unused
        # 0x1e is unused

        self.grayPalChunk = None
        if chunks[0x1f]:
            self.grayPalChunk = GrayPalChunk(chunks[0x1f], self)

        # 0x20 is unused
        # 0x21 is unused
        # 0x22 is unused
        # 0x23 is mesh animation info
        # 0x24..0x2b = animated meshes 0-7

    def write(self):
        if self.meshChunk != None:
            self.chunks[0x10] = self.meshChunk.toBin()
        if self.colorPalChunk != None:
            self.chunks[0x11] = self.colorPalChunk.toBin()
        if self.lightChunk != None:
            self.chunks[0x19] = self.lightChunk.toBin()
        if self.terrainChunk != None:
            self.chunks[0x1a] = self.terrainChunk.toBin()
        if self.texAnimChunk != None:
            self.chunks[0x1b] = self.texAnimChunk.toBin()
        if self.palAnimChunk != None:
            self.chunks[0x1c] = self.palAnimChunk.toBin()
        if self.grayPalChunk != None:
            self.chunks[0x1f] = self.grayPalChunk.toBin()
        if self.visAngleChunk != None:
            # meshChunk has the polygons (but when I read from blender, will it?)
            # I could hold the reference to 'res' upon meshChunk ctor ... meh
            self.chunks[0x2c] = self.visAngleChunk.toBin(self.meshChunk)

        # now write the header
        ofs = sizeof(self.header)
        for (i, chunk) in enumerate(self.chunks):
            if chunk:
                self.header[i] = ofs
                ofs += len(chunk)
            else:
                self.header[i] = 0
        data = bytes(self.header)
        for chunk in self.chunks:
            data += chunk
        newNumSectors = countSectors(len(data))
        if newNumSectors > self.numSectors:
            print('WARNING: File has grown from %u sectors to %u sectors!' % (self.numSectors, newNumSectors))
        elif newNumSectors < self.numSectors:
            print('Note: File has shrunk from %u sectors to %u sectors.' % (self.numSectors, newNumSectors))
        self.numSectors = newNumSectors
        file = open(self.filepath, 'wb')
        file.write(data)
        file.close()

class TexBlob(ResourceBlob):
    width = 256
    height = 1024
    # can python do this?
    #rowsize = width >> 1
    def __init__(self, record, filename, mapdir):
        # maybe not?
        self.rowsize = self.width >> 1
        super().__init__(record, filename, mapdir)
        data = self.readData()

        # expand the 8-bits into separate 4-bits into an image double array
        # this isn't grey, it's indexed into one of the 16 palettes.
        # TODO store this just [] instead of [][]
        pix44 = (TwoNibbles * len(data)).from_buffer_copy(data)
        # pix8 = [colorIndex] in [0,15] integers
        # which is slower?
        """
        pix8 = [
            colorIndex
            for y in range(self.height)
            for x in range(self.rowsize)
            for colorIndex in pix44[x + y * self.rowsize].toTuple()
        ]
        """
        # vs
        pix8 = [0] * (self.width * self.height)
        dsti = 0
        for srci in range(self.height * self.rowsize):
            lohi = pix44[srci]
            pix8[dsti] = lohi.lo
            dsti += 1
            pix8[dsti] = lohi.hi
            dsti += 1

        # here's the indexed texture, though it's not attached to anything
        self.indexImg = bpy.data.images.new(self.filename + ' Tex Indexed', width=self.width, height=self.height)
        self.indexImg.alpha_mode = 'NONE'
        self.indexImg.colorspace_settings.name = 'Raw'
        self.indexImg.pixels = [
            ch
            for colorIndex in pix8
            for ch in (
                (colorIndex+.5)/16.,
                (colorIndex+.5)/16.,
                (colorIndex+.5)/16.,
                1.
            )
        ]

    def writeTexture(self):
        pixRGBA = self.indexImg.pixels
        data = b''
        for y in range(self.height):
            for x in range(self.rowsize):
                data += bytes(TwoNibbles(
                    int(16. * pixRGBA[0 + 4 * (0 + 2 * (x + self.rowsize * y))]),
                    int(16. * pixRGBA[0 + 4 * (1 + 2 * (x + self.rowsize * y))])
                ))
        assert len(self.textureFilenames) == 1
        file = open(self.textureFilenames[0], 'wb')
        file.write(data)
        file.close()


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
        self.readGNS(filepath)

        progress.enter_substeps(3, "Parsing GNS file...")

        # bail out if we're just reading headers and not building scenes
        # TODO separate the GNS reading from the Blender building?
        if context == None:
            return

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

    # GaneshaDx here:
    # iters thru whole file, reading GNSRecord's as 20-bytes (or whatever remains)
    #  filters out only the tex & mesh res.
    # sort resources by sector
    def readGNS(self, filepath):
        #mapNum = int(filepath[-7:-4])
        file = open(filepath, 'rb')
        allRecords = []
        while True:
            #def readStruct(file, struct):
            #    return struct.from_buffer_copy(file.read(sizeof(struct)))
            #r = readStruct(file, GNSRecord)
            # but it could be incomplete right?
            # file.read(numBytes) will fail gracefully
            # but I think ctype.from_buffer_copy won't ...
            sdata = file.read(sizeof(GNSRecord))
            sdata = sdata + b'\0' * (sizeof(GNSRecord) - len(sdata)) # pad?
            r = GNSRecord.from_buffer_copy(sdata)
            if r.resourceFlag == 1 and r.resourceType == RESOURCE_EOF:
                break
            allRecords.append(r)
        file.close()

        allRecords.sort(key=lambda a: a.sector)

        # now using sorted sectors and file suffixes, map all records to their files
        allSectors = sorted(set(r.sector for r in allRecords))

        # get all files in the same dir with matching prefix ...
        allResFilenames = []
        for fn in os.listdir(self.mapdir):
            if fn != self.filename and os.path.splitext(fn)[0] == self.nameroot:
                allResFilenames.append(fn)

        # sort by filename suffix
        allResFilenames.sort(key=lambda fn: int(os.path.splitext(fn)[1][1:]))
        assert len(allSectors) == len(allResFilenames)

        # map from sector back to resource filename
        self.filenameForSector = {}
        for (sector, resFn) in zip(allSectors, allResFilenames):
            self.filenameForSector[sector] = resFn

        #print(allSectors)
        #print(allRes)

        # now, here, per resource file, load *everything* you can
        # I'm gonna put everything inside blender first and then sort it out per-scene later

        self.allTexRes = []
        self.allMeshRes = []
        for (i, r) in enumerate(allRecords):
            print('GNS record', self.filenameForSector[r.sector], str(r), end='')
            if r.resourceType == RESOURCE_TEXTURE:
                print('...tex')
                self.allTexRes.append(TexBlob(
                    r,
                    self.filenameForSector[r.sector],
                    self.mapdir
                ))
            elif (r.resourceType == RESOURCE_MESH_INIT
                or r.resourceType == RESOURCE_MESH_REPL
                or r.resourceType == RESOURCE_MESH_ALT):
                res = NonTexBlob(
                    r,
                    self.filenameForSector[r.sector],
                    self.mapdir
                )
                print('...res w/chunks '+str([i for i, e in enumerate(res.header) if e != 0]))
                self.allMeshRes.append(res)
            # else keep it anywhere?

        # enumerate unique (arrangement,night,weather) tuples
        # sort them too, so the first one is our (0,0,0) initial state
        self.allMapStates = sorted(set(r.record.getMapState() for r in self.allMeshRes))
        #print('all map states:')
        #print('arrangement / night / weather:')
        #for s in self.allMapStates:
        #    print(s)
        if len(self.allMapStates) == 0:
            print("sorry there's no map states for this map...")
            raise "raise"


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
        #mapState = self.allMapStates[0]
        #mapState = self.allMapStates[1]
        #mapState = (1,1,4)
        # are all configurations defined for all maps?
        # TODO

        # now set the map state to its default: arrangement==0, weather==0 night==0
        # what about maps that don't have this particular state?
        # how about instead, sort all states, and pick the one closest to this ...
        self.nonTexRess = list(filter(
            lambda r: r.record.getMapState() == mapState
                # ... right?  I also want the init mesh in here, right?
                or r.record.resourceType == RESOURCE_MESH_INIT,
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
                mat = bpy.data.materials.new('GNS Mat Tex w Pal '+str(i))
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
            isTexd = matPerPal != None and (isinstance(s, TriTex) or isinstance(s, QuadTex))
            vs = vertexesForPoly(s)
            n = len(vs)
            for v in vs:
                meshVtxPos.append(v.pos.toTuple())

                if isTexd:
                    meshVtxTCs.append((
                        (v.texcoord.x + .5) / TexBlob.width,
                        (256 * s.texFace.page + v.texcoord.y + .5) / TexBlob.height
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
            self.terrainChunk.tmeshObj.matrix_world = global_matrix
            # once again, is this applied before or after matrix_world? before or after view_later.update() ?
            # looks like it is in blender coordinates, i.e. z-up
            self.terrainChunk.tmeshObj.location = 0, 0, .01
            newObjects.append(self.terrainChunk.tmeshObj)

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

        map = Map(
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

        for i in range(1,len(map.collections)):
            set_collection_viewport_visibility(context, map.collections[i], visibility=False)
        set_collection_viewport_visibility(context, map.collections[0], visibility=True)

        # ... and those 50 lines of code are what is needed to just hide an object in the viewport

    return {'FINISHED'}
