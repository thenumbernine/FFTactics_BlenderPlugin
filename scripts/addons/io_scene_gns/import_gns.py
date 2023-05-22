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
    # why isn't there an easy way to do this?
    def toTuple(self):
        return tuple(getattr(self, x[0]) for x in self._fields_)

# list of these in the GNS file that direct us to other resources
# what to call it? resource? resource header?
class GNSRecord(FFTStruct):
    _pack_ = 1
    _fields_ = [
        # GaneshaDx looks at only the low byte here,
        # and says only 0x22, 0x30, and 0x70 are acceptable
        ('sig', c_uint16),

        # 0 = primary
        # 1 = secondary
        # from the consts in here I'd say there's up to ==5 ?
        # 'arrangement' eh?  'config' ?
        ('arrangement', c_uint8),

        ('unknown3', c_uint8, 4),

        # 0..4 by the enums in python Ganesha
        # from 'none' to 'strong'
        ('weather', c_uint8, 3),

        # 0 = day
        # 1 = night
        ('isNight', c_uint8, 1),    # day vs night?

        ('resourceFlag', c_uint8),  # always 1?

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

        ('unknown6', c_uint16),
        ('sector', c_uint32),
        ('size', c_uint32),         # file size, rounded up to 2k block
        ('unknownA', c_uint32),
    ]

    # return the tuple of arrangement, isNight, weather which are used to uniquely identify ... bleh
    def getMapState(self):
        return (self.arrangement, self.isNight, self.weather)

assert sizeof(GNSRecord) == 20

class MeshHeader(FFTStruct):
    _pack_ = 1
    _fields_ = [
        ('numTriTex', c_uint16),
        ('numQuadTex', c_uint16),
        ('numTriUntex', c_uint16),
        ('numQuadUntex', c_uint16),
    ]

class VertexPos(FFTStruct):
    _pack_ = 1
    _fields_ = [
        ('x', c_int16),
        ('y', c_int16),
        ('z', c_int16),
    ]

class Normal(FFTStruct):
    _pack_ = 1
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
    _pack_ = 1
    _fields_ = [
        ('x', c_uint8),
        ('y', c_uint8),
    ]
assert sizeof(TexCoord) == 2

# textured-triangle face information
class TriTexFace(FFTStruct):
    _pack_ = 1
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
# matches TriTexFace
class QuadTexFace(FFTStruct):
    _pack_ = 1
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
    _pack_ = 1
    _fields_ = [
        ('x', c_uint8),
        ('y', c_uint8, 1),
        ('z', c_uint8, 7),
    ]
assert sizeof(TilePos) == 2

def clamp(x,mn,mx):
    return max(mn, min(mx, x))

class RGBA5551(FFTStruct):
    _pack_ = 1
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
    _pack_ = 1
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
    _pack_ = 1
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
    _pack_ = 1
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
    _pack_ = 1
    _fields_ = [
        ('lo', c_uint8, 4),
        ('hi', c_uint8, 4),
    ]

################################ fft/map/gns.py ################################

# GaneshaDx: texture resources:
RESOURCE_TEXTURE = 0x17
# GaneshaDx: mesh resources:
RESOURCE_MESH_INIT = 0x2e # Always used with (0x22, 0, 0, 0). Always a big file.
RESOURCE_MESH_REPL = 0x2f # Always used with (0x30, 0, 0, 0). Usually a big file.
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

class MeshBlob(ResourceBlob):
    def __init__(self, record, filename, mapdir):
        super().__init__(record, filename, mapdir)
        data = self.readData()
        self.numSectors = countSectors(len(data))

        numChunks = 49
        chunkNames = {
            0x10 : 'mesh',
            0x2c : 'vis angles',
            0x11 : 'color pals',
            0x19 : 'lights',
            0x1a : 'terrain',
            0x1f : 'grey pals',
        }

        self.chunks = [None] * numChunks

        self.header = (c_uint32 * numChunks).from_buffer_copy(data)

        self.chunks = [None] * numChunks
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
                self.chunks[i] = data[begin:end]

        # now while we're here, parse the respective chunks
        data = None
        ofs = 0

        def setChunk(x, ofs0=0):
            nonlocal ofs
            ofs = ofs0
            nonlocal data
            data = self.chunks[x]
            return data

        def read(cl):
            nonlocal ofs
            res = cl.from_buffer_copy(data[ofs:ofs+sizeof(cl)])
            ofs += sizeof(cl)
            return res

        # reading from chunk 0x10
        triTexVtxs = None
        if setChunk(0x10):
            hdr = read(MeshHeader)
            triTexVtxs = read(VertexPos * (3 * hdr.numTriTex))
            quadTexVtxs = read(VertexPos * (4 * hdr.numQuadTex))
            triUntexVtxs = read(VertexPos * (3 * hdr.numTriUntex))
            quadUntexVtxs = read(VertexPos * (4 * hdr.numQuadUntex))
            triTexNormals = read(Normal * (3 * hdr.numTriTex))
            quadTexNormals = read(Normal * (4 * hdr.numQuadTex))
            triTexFaces = read(TriTexFace * hdr.numTriTex)
            quadTexFaces = read(QuadTexFace * hdr.numQuadTex)
            triUntexUnknowns = read(c_uint32 * hdr.numTriUntex) # then comes unknown 4 bytes per untex-tri
            quadUntexUnknowns = read(c_uint32 * hdr.numQuadUntex) # then comes unknown 4 bytes per untex-quad
            triTexTilePos = read(TilePos * hdr.numTriTex) # then comes terrain info 2 bytes per tex-tri
            quadTexTilePos = read(TilePos * hdr.numQuadTex) # then comes terrain info 2 bytes per tex-quad
            # and that's it from chunk 0x10

        # reading chunk 0x2c
        if setChunk(0x2c, 0x380):
            # from the 'writeVisAngles' function looks like this is written to a 1024 byte block always
            triTexVisAngles = read(c_uint16 * 512)
            # ... and this is a 1536 byte block always
            quadTexVisAngles = read(c_uint16 * 768)
            triUntexVisAngles = read(c_uint16 * 64)
            quadUntexVisAngles = read(c_uint16 * 256)
            # does this mean we can only have 512 tex'd tris/tex'd quads/untex'd tris/untex'd quads?
            # GaneshaDx has these constants:
            #MaxTexturedTriangles = 360
            #MaxTexturedQuads = 710
            #MaxUntexturedTriangles = 64
            #MaxUntexturedQuads = 256
            # why are GaneshaDx's textured tri and quad counts lower than original python Ganesha's?
            # done reading chunk 0x2c

        # TODO put this method in sub-obj of chunk11
        # reading chunk 0x11
        if setChunk(0x11):
            numColorPals = 16
            numColorsPerPal = 16
            colorPals = []
            for i in range(numColorPals):
                colorPals.append(read(RGBA5551 * numColorsPerPal))
            # done reading chunk 0x11

            # write out the palettes as images themselves
            self.colorPalImgs = [None] * len(colorPals)
            for (i, pal) in enumerate(colorPals):
                self.colorPalImgs[i] = bpy.data.images.new(self.filename + 'Pal Tex '+str(i), width=numColorsPerPal, height=1)
                self.colorPalImgs[i].pixels = [
                    ch
                    for color in pal
                    for ch in color.toTuple()
                ]

        # reading chunk 0x1f
        if setChunk(0x1f):
            self.grayPals = []
            for i in range(16):
                self.grayPals.append(read(RGBA5551 * 16))
            # done reading chunk 0x1f

        # reading chunk 0x19
        if setChunk(0x19):
            self.dirLightColors = read(LightColors)
            self.dirLightDirs = read(VertexPos * 3) # could be Normal structure as well, but both get normalized to the same value in the end
            self.ambientLightColor = read(RGB888)
            self.backgroundColors = read(RGB888 * 2)
            # done reading chunk 0x19

        # reading chunk 0x1a
        if setChunk(0x1a):
            terrainSize = read(c_uint8 * 2)  # (sizeX, sizeZ)
            # weird, it leaves room for 256 total tiles for the first xz plane, and then the second is packed?
            terrainTileSrc = read(TerrainTile * (256 + terrainSize[0] * terrainSize[1]))
            # done reading chunk 0x1a

            # convert the terrainTiles from [z * terrainSize[0] + x] w/padding for y to [y][z][x]
            self.terrainSize = terrainSize
            self.terrainTiles = []
            for y in range(2):
                level = []
                for z in range(self.terrainSize[1]):
                    row = []
                    for x in range(self.terrainSize[0]):
                        row.append(terrainTileSrc[256 * y + z * terrainSize[0] + x])
                    level.append(row)
                self.terrainTiles.append(level)

        # now for aux calcs
        if triTexVtxs != None:
            bboxMin = [math.inf] * 3
            bboxMax = [-math.inf] * 3
            for v in list(triTexVtxs) + list(quadTexVtxs) + list(triUntexVtxs) + list(quadUntexVtxs):
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
            for i in range(hdr.numTriTex):
                self.triTexs.append(TriTex(
                    triTexVtxs[3*i:3*(i+1)],
                    triTexNormals[3*i:3*(i+1)],
                    triTexFaces[i],
                    triTexTilePos[i],
                    triTexVisAngles[i]
                ))

            self.quadTexs = []
            for i in range(hdr.numQuadTex):
                self.quadTexs.append(QuadTex(
                    quadTexVtxs[4*i:4*(i+1)],
                    quadTexNormals[4*i:4*(i+1)],
                    quadTexFaces[i],
                    quadTexTilePos[i],
                    quadTexVisAngles[i]
                ))

            self.triUntexs = []
            for i in range(hdr.numTriUntex):
                self.triUntexs.append(TriUntex(
                    triUntexVtxs[3*i:3*(i+1)],
                    triUntexUnknowns[i],
                    triUntexVisAngles[i]
                ))

            self.quadUntexs = []
            for i in range(hdr.numQuadUntex):
                self.quadUntexs.append(QuadUntex(
                    quadUntexVtxs[4*i:4*(i+1)],
                    quadUntexUnknowns[i],
                    quadUntexVisAngles[i]
                ))

    # old write code ... but TODO only write what you have or something i guess idk
    def writeHeader(self):
        offset = sizeof(self.header)
        for (i, chunk) in enumerate(self.chunks):
            if chunk:
                self.header[i] = offset
                offset += len(chunk)
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

    def writeRes(self):
        self.writePolygons()
        self.writeVisAngles()
        self.writeColorPalettes()
        self.writeGrayPalettes()
        self.writeDirLights()
        self.writeTerrain()

    def writePolygons(self):
        data = bytes(self.meshHdr)
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
        self.chunks[0x10] = data

    def writeVisAngles(self):
        triTexVisAngles = b''
        for polygon in self.triTexs:
            triTexVisAngles += bytes(polygon.visAngles)
        triTexVisAngles += b'\0' * (1024 - len(triTexVisAngles))

        quadTexVisAngles = b''
        for polygon in self.quadTexs:
            quadTexVisAngles += bytes(polygon.visAngles)
        quadTexVisAngles += b'\0' * (1536 - len(quadTexVisAngles))

        triUntexVisAngles = b''
        for polygon in self.triUntexs:
            triUntexVisAngles += bytes(polygon.visAngles)
        triUntexVisAngles += b'\0' * (128 - len(triUntexVisAngles))

        quadUntexVisAngles = b''
        for polygon in self.quadUntexs:
            quadUntexVisAngles += bytes(polygon.visAngles)
        quadUntexVisAngles += b'\0' * (512 - len(quadUntexVisAngles))

        ofs = 0x380
        olddata = self.chunks[0x2c]
        self.chunks[0x2c] = (
              olddata[:ofs]
            + triTexVisAngles
            + quadTexVisAngles
            + triUntexVisAngles
            + quadUntexVisAngles
            + olddata[ofs + len(data):]
        )

    # TODO put this method in sub-obj of chunk11
    def writeColorPalettes(self):
        data = b''
        if hasattr(self, 'colorPalImgs'):
            for img in self.colorPalImgs:
                pixRGBA = img.pixels
                for i in range(len(pixRGBA)/4):
                    data += bytes(RGBA5551.fromRGBA(
                        pixRGBA[0 + 4 * i],
                        pixRGBA[1 + 4 * i],
                        pixRGBA[2 + 4 * i],
                        pixRGBA[3 + 4 * i]
                    ))
        self.chunks[0x11] = data

    def writeGrayPalettes(self):
        data = b''
        for palette in self.grayPals:
            data += bytes(palette)
        self.chunks[0x11] = data

    def writeDirLights(self):
        data = (
              bytes(self.dirLightColors)
            + bytes(self.dirLightDirs)
            + bytes(self.ambientLightColors)
            + bytes(self.backgroundColors)
        )

        ofs = 0
        olddata = self.chunks[0x19]
        self.chunks[0x19] = (
            olddata[:ofs]
            + data
            + olddata[ofs + len(data):]
        )

    def writeTerrain(self):
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
        ofs = 0
        olddata = self.chunks[0x1a]
        self.chunks[0x1a] = (
            olddata[:ofs]
            + data
            + olddata[ofs + len(data):]
        )

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
    def __init__(self, filepath, mapConfigIndex, dayNight, weather):
        self.readGNS(filepath)

        self.setConfig(mapConfigIndex, dayNight, weather)

        # copy texture fields
        # TODO copy refs to blender objects associated with these fields

        if len(self.texRess) == 0:
            print("no texture...")
            raise "raise"
        res = self.texRess[0]
        self.indexImg = res.indexImg

        # this is like an overlay filesystem right?
        # a unique (arrangement, day/night, weather) will have a unique texture & mesh resource
        # (also the base mesh-resource?)
        # and the multiple mesh-resources each have a list of offsets that, when all superimposed, give the level its complete set of offsets into resoruces (mesh, lights, terrain, etc)
        # ... if the "mesh resource" includes mesh, terrain, lights ... maybe pick a better name for it? like "level resource" ?
        def setResField(field):
            for res in self.meshRess:
                if hasattr(res, field):
                    value = getattr(res, field)
                    # TODO should I ever have None be valid?
                    if value != None:
                        setattr(self, field, value)
                        return
        for field in [
            # 0x11
            'colorPalImgs',
            # 0x1f
            'grayPals',
            # 0x19
            'dirLightColors',
            'dirLightDirs',
            'ambientLightColor',
            'backgroundColors',
            # 0x1a
            'terrainSize',
            'terrainTiles',
            # aux
            'bbox',
            'center',
            'triTexs',
            'quadTexs',
            'triUntexs',
            'quadUntexs',
        ]:
            setResField(field)

    # GaneshaDx here:
    # iters thru whole file, reading GNSRecord's as 20-bytes (or whatever remains)
    #  filters out only the tex & mesh res.
    # sort resources by sector
    def readGNS(self, filepath):
        #mapNum = int(filepath[-7:-4])
        self.mapdir = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        namesuffix = os.path.splitext(filename)[0]
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
            if fn != filename and os.path.splitext(fn)[0] == namesuffix:
                allResFilenames.append(fn)

        # sort by filename suffix
        allResFilenames.sort(key=lambda fn: int(os.path.splitext(fn)[1][1:]))
        assert len(allSectors) == len(allResFilenames)

        # map from sector back to resource filename
        self.filenameForSector = {}
        for (sector, filename) in zip(allSectors, allResFilenames):
            self.filenameForSector[sector] = filename

        #print(allSectors)
        #print(allRes)

        # now, here, per resource file, load *everything* you can
        # I'm gonna put everything inside blender first and then sort it out per-scene later

        self.allTexRes = []
        self.allMeshRes = []
        for r in allRecords:
            print('GNS record', r.sector, self.filenameForSector[r.sector], r.resourceType, r.arrangement, r.isNight, r.weather)
            if r.resourceType == RESOURCE_TEXTURE:
                self.allTexRes.append(TexBlob(
                    r,
                    self.filenameForSector[r.sector],
                    self.mapdir
                ))
            elif (r.resourceType == RESOURCE_MESH_INIT
                or r.resourceType == RESOURCE_MESH_REPL
                or r.resourceType == RESOURCE_MESH_ALT):
                self.allMeshRes.append(MeshBlob(
                    r,
                    self.filenameForSector[r.sector],
                    self.mapdir
                ))
            # else keep it anywhere?

        # enumerate unique (arrangement,night,weather) tuples
        # sort them too, so the first one is our (0,0,0) initial state
        allMapStates = sorted(set(r.record.getMapState() for r in self.allMeshRes))
        print('all map states:')
        print('arrangement / night / weather:')
        for s in allMapStates:
            print(s)
        if len(allMapStates) == 0:
            print("sorry there's no map states for this map...")
            raise "raise"


    # TODO don't set upon init
    # instead cycle thru *all* configs
    # and make a new scene/group/whatever for each
    # reuse blender objs <-> fft resources as you go
    def setConfig(self, mapConfigIndex, dayNight, weather):

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

        print("setting config", mapConfigIndex, dayNight, weather)
        # now pick one ...
        # or somehow let the user decide which one to pick?
        curMapState = (mapConfigIndex, dayNight, weather)
        #curMapState = allMapStates[0]
        #curMapState = allMapStates[1]
        #curMapState = (1,1,4)
        # are all configurations defined for all maps?
        # TODO

        # now set the map state to its default: arrangement==0, weather==0 night==0
        # what about maps that don't have this particular state?
        # how about instead, sort all states, and pick the one closest to this ...
        self.meshRess = list(filter(
            lambda r: r.record.getMapState() == curMapState
                # ... right?  I also want the init mesh in here, right?
                or r.record.resourceType == RESOURCE_MESH_INIT,
            self.allMeshRes))
        self.texRess = list(filter(
            lambda r: r.record.getMapState() == curMapState,
            self.allTexRes))

        # ... what order does the records() chunks[] system work?
        #self.meshRess.reverse()

        # map from mesh and texture record to mesh filename
        getPathForRes = lambda r: r.filename
        print('meshFilenames', list(map(getPathForRes, self.meshRess)))
        print('textureFilenames', list(map(getPathForRes, self.texRess)))

    def polygons(self):
        return self.triTexs + self.quadTexs + self.triUntexs + self.quadUntexs

################################ import_gns ################################

def load(context,
         filepath,
         *,
         global_scale_x=28.0,
         global_scale_y=24.0,
         global_scale_z=28.0,
         relpath=None,
         global_matrix=None,
         mapConfigIndex=0,
         dayNight=0,
         weather=0
         ):
    with ProgressReport(context.window_manager) as progress:

        progress.enter_substeps(1, "Importing GNS %r..." % filepath)

        filename = os.path.splitext((os.path.basename(filepath)))[0]

        if global_matrix is None:
            global_matrix = mathutils.Matrix()

        progress.enter_substeps(3, "Parsing GNS file...")

        map = Map(filepath, mapConfigIndex, dayNight, weather)

        # deselect all
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        newObjects = []  # put new objects here

        view_layer = context.view_layer
        collection = view_layer.active_layer_collection.collection

        ### make the material for textured faces

        uniqueMaterials = {}

        # Write out the indexed image with each 16 palettes applied to it
        # This can only be done once the texture and color-palette MeshBlob have been read in
        matTexNamePerPal = [None] * len(map.colorPalImgs)
        for (i, pal) in enumerate(map.colorPalImgs):
            name ='GNS Mat Tex w Pal '+str(i)
            matTexNamePerPal[i] = name

            # get image ...
            # https://blender.stackexchange.com/questions/643/is-it-possible-to-create-image-data-and-save-to-a-file-from-a-script
            mat = uniqueMaterials[name] = bpy.data.materials.new(name)
            matWrap = node_shader_utils.PrincipledBSDFWrapper(mat, is_readonly=False)
            matWrap.use_nodes = True

            # https://blender.stackexchange.com/questions/157531/blender-2-8-python-add-texture-image
            palNode = mat.node_tree.nodes.new('ShaderNodeTexImage')
            palNode.image = map.colorPalImgs[i]
            palNode.interpolation = 'Closest'
            palNode.location = (-300, 0)

            indexNode = mat.node_tree.nodes.new('ShaderNodeTexImage')
            indexNode.image = map.indexImg
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

        matWOTexName = 'GNS Material Untextured'
        matWOTex = uniqueMaterials[matWOTexName] = bpy.data.materials.new(matWOTexName)
        matWOTexWrap = node_shader_utils.PrincipledBSDFWrapper(matWOTex, is_readonly=False)
        matWOTexWrap.use_nodes = True
        matWOTexWrap.specular = 0
        matWOTexWrap.base_color = (0., 0., 0.)


        ### make the mesh

        material_mapping = {name: i for i, name in enumerate(uniqueMaterials)}
        materials = [None] * len(uniqueMaterials)
        for name, index in material_mapping.items():
            materials[index] = uniqueMaterials[name]

        mesh = bpy.data.meshes.new(filename + ' Mesh')
        for material in materials:
            mesh.materials.append(material)

        # flip face order
        # I guess I could just set the cw vs ccw ...
        # also handle FFT tristrip => Blender quads
        def vertexesForPoly(poly):
            if len(poly.vtxs) == 4:
                return [poly.vtxs[2], poly.vtxs[3], poly.vtxs[1], poly.vtxs[0]]  # cw => ccw and tristrip -> quad
            return [poly.vtxs[2], poly.vtxs[1], poly.vtxs[0]]                    # cw front-face => ccw front-face

        meshVtxPos = []
        meshVtxNormals = []
        meshVtxTCs = []
        faces = []  # tuples of the faces
        vi = 0
        vti = 0
        for s in map.polygons():
            isTexd = isinstance(s, TriTex) or isinstance(s, QuadTex)
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
                    # if I exclude the texcoords and normals on the faces that don't use them then I get this error in blender:
                    #  Error: Array length mismatch (got 6615, expected more)
                    # should I put the non-texcoord/normal'd faces in a separate mesh?
                    # TODO give them their own material
                    meshVtxTCs.append((0,0))
                    meshVtxNormals.append((0,0,0))

            # turn all polys into fans
            for i in range(1,n-1):
                face_vert_loc_indices = [vi+0, vi+i, vi+i+1]
                #if isTexd:
                face_vert_nor_indices = [vti+0, vti+i, vti+i+1]
                face_vert_tex_indices = [vti+0, vti+i, vti+i+1]
                faces.append((
                    face_vert_loc_indices,
                    face_vert_nor_indices,
                    face_vert_tex_indices,
                    matTexNamePerPal[s.texFace.pal] if isTexd else matWOTexName
                ))
            vi+=n
            #if isTexd:
            vti+=n

        loops_vert_idx = tuple(vidx for (face_vert_loc_indices, _, _, _) in faces for vidx in face_vert_loc_indices)

        fgon_edges = set()
        tot_loops = 3 * len(faces)

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

        tmesh = bpy.data.meshes.new(filename + ' Terrain')
        tmeshVtxs = []
        tmeshEdges = []
        tmeshFaces = []
        tilesFlattened = []
        for y in range(2):
            for z in range(map.terrainSize[1]):
                for x in range(map.terrainSize[0]):
                    tile = map.terrainTiles[y][z][x]
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
        tmeshObj.matrix_world = global_matrix
        tmeshObj.hide_render = True
        newObjects.append(tmeshObj)


        # custom per-face attributes for the terrain:
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


        # directional lights
        # https://stackoverflow.com/questions/17355617/can-you-add-a-light-source-in-blender-using-python
        for i in range(3):
            lightName = filename + ' Light '+str(i)
            lightData = bpy.data.lights.new(name=lightName, type='SUN')
            lightData.energy = 20       # ?
            lightData.color = map.dirLightColors.ithToTuple(i)
            lightData.angle = math.pi
            lightObj = bpy.data.objects.new(name=lightName, object_data=lightData)
            # matrix_world rotate y- to z+ ...
            lightObj.matrix_world = global_matrix
            # alright, how come with mesh, I can assign the matrix_world then assign the scale, and it rotates scales
            # but with this light, I apply matrix_world then I apply location, and the matrix_world is gone?
            # python is a languge without any block scope and with stupid indent rules.  it encourages polluting function namespaces.
            lightPos = (
                map.bbox[0][0] / global_scale_x + i,
                map.bbox[0][2] / global_scale_y,
                -map.bbox[0][1] / global_scale_z
            )
            lightObj.location = lightPos[0], lightPos[1], lightPos[2]
            # calculate lightObj Euler angles by dirLightDirs
            # TODO figure out which rotates which...
            dir = map.dirLightDirs[i].toTuple()
            print('light dir', dir)
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
            newObjects.append(lightObj)


        # ambient light?  in blender?
        # https://blender.stackexchange.com/questions/23884/creating-cycles-background-light-world-lighting-from-python
        # seems the most common way is ...
        # ... overriding the world background
        """
        world = bpy.data.worlds['World']
        background = world.node_tree.nodes['Background']
        background.inputs[0].default_value[:3] = map.ambientLightColor.toTuple()
        background.inputs[1].default_value = 5.
        """
        # but you can just do that once ... what if I want to load multiple map cfgs at a time?
        lightName = filename+' Ambient'
        lightData = bpy.data.lights.new(name=lightName, type='SUN')
        lightData.energy = 20       # ?
        lightData.color = map.ambientLightColor.toTuple()
        lightData.angle = math.pi
        lightObj = bpy.data.objects.new(name=lightName, object_data=lightData)
        lightObj.matrix_world = global_matrix
        lightPos = (
            map.bbox[0][0] / global_scale_x + 3,
            map.bbox[0][2] / global_scale_y,
            -map.bbox[0][1] / global_scale_z
        )
        lightObj.location = lightPos[0], lightPos[1], lightPos[2]
        newObjects.append(lightObj)


        # setup bg mesh mat

        bgMat = bpy.data.materials.new(filename + ' Bg Mat')
        bgMatWrap = node_shader_utils.PrincipledBSDFWrapper(bgMat, is_readonly=False)
        bgMatWrap.use_nodes = True

        bsdf = bgMat.node_tree.nodes['Principled BSDF']
        bgMixNode = bgMat.node_tree.nodes.new('ShaderNodeMixRGB')
        bgMixNode.location = (-200, 0)
        bgMixNode.inputs[1].default_value[:3] = map.backgroundColors[0].toTuple()
        bgMixNode.inputs[2].default_value[:3] = map.backgroundColors[1].toTuple()
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
        bgmesh = bpy.data.meshes.new(filename + ' Bg')
        bgmesh.materials.append(bgMat)
        bgmeshObj = bpy.data.objects.new(bgmesh.name, bgmesh)
        # center 'y' is wayyy up ...
        #bgmeshObj.location = map.center[0], map.center[1], map.center[2]
        bgmeshObj.location = 5, 5, 5
        bgmeshObj.scale = 20., 20., 20.

        # make the mesh a sphere and smooth
        # do this before objects.link ... ?
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=5)
        # normal_flip not working?
        for f in bm.faces:
            f.normal_flip()
        bm.normal_update()

        bm.to_mesh(bgmeshObj.data)
        bm.free()

        # create-object for the bmesh
        collection.objects.link(bgmeshObj)
        bgmeshObj.select_set(True)

        #bpy.ops.object.modifier_add(type='SUBSURF')
        bpy.ops.object.shade_smooth()

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

        view_layer.update()


        progress.leave_substeps("Done.")
        progress.leave_substeps("Finished importing: %r" % filepath)

    return {'FINISHED'}
