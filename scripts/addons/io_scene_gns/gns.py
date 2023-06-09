import math
import os.path
from ctypes import *

class FFTData:
    _pack_ = 1
    # why isn't there an easy way to do this?
    def toTuple(self):
        return tuple(getattr(self, x[0]) for x in self._fields_)

    # override this to change serialization
    @staticmethod
    def intToStr(x):
        return str(x)#f'{x:d}'

    def __str__(self):
        return '{'+', '.join(x[0]+'='+FFTData.intToStr(getattr(self, x[0])) for x in self._fields_)+'}'

""" hmm 'new in 3.11' looks like Blender (python 3.10.9) needs to upgrade?
class FFTUnion(LittleEndianUnion, FFTData):
    pass
"""

class FFTStruct(LittleEndianStructure, FFTData):
    pass

################################ resousre files ################################

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

class UnknownBlob(ResourceBlob):
    def __init__(self, record, filename, mapdir):
        super().__init__(record, filename, mapdir)

################################ texture resousre files ################################

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
        pix44 = (TwoNibbles * len(data)).from_buffer_copy(data)
        # self.pixels = [colorIndex] in [0,15] integers
        # which is faster?
        """
        pix8 = [
            colorIndex
            for y in range(self.height)
            for x in range(self.rowsize)
            for colorIndex in pix44[x + y * self.rowsize].toTuple()
        ]
        """
        # vs
        self.pixels = [0] * (self.width * self.height)
        dsti = 0
        for srci in range(self.height * self.rowsize):
            lohi = pix44[srci]
            self.pixels[dsti] = lohi.lo
            dsti += 1
            self.pixels[dsti] = lohi.hi
            dsti += 1

    def writeTexture(self, filepath):
        data = b''
        for y in range(self.height):
            for x in range(self.rowsize):
                data += bytes(TwoNibbles(
                    int(self.pixels[0 + 2 * (x + self.rowsize * y)]),
                    int(self.pixels[1 + 2 * (x + self.rowsize * y)])
                ))
        file = open(filepath, 'wb')
        file.write(data)
        file.close()

################################ non-texture resousre structs ################################


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
class Tile(FFTStruct):
    _fields_ = [
        # 00:
        ('surfaceType', c_uint8, 6),
        ('unk0_6', c_uint8, 2),
        # 01:
        ('unk1', c_uint8),
        # 02:
        ('halfHeight', c_uint8),    # in half-tiles
        # 03:
        ('slopeHeight', c_uint8, 5),
        ('depth', c_uint8, 3),      # in half-tiles too?
        # 04:
        ('slopeType', c_uint8),
        # 05:
        # TODO include this
        ('thickness', c_uint8),
        # 06:
        ('cantCursor', c_uint8, 1),
        ('cantWalk', c_uint8, 1),
        ('unk6_2', c_uint8, 6),

        # 07:
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
assert sizeof(Tile) == 8

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

# TODO is there a way to read ctypes fixed endianness outside a struct/union?
class VisAngleFlags(FFTStruct):
    _fields_ = [
        ('v', c_uint16),
    ]

# forcing little-endian-ness via ctypes struct
class UntexUnknown(FFTStruct):
    _fields_ = [
        ('v', c_uint32),
    ]

# chunks used in maps 001 thru 119:
# in hex: 10, 11, 13, 19, 1a, 1b, 1c, 1f, 23, 24, 25, 26, 27, 28, 29, 2a, 2b, 2c
# missing:
# in hex: 12, 14, 15, 16, 17, 18, 1d, 1e, 20, 21, 22
# ... seems like the first 64 bytes are used for something else
NUM_CHUNKS = 49

CHUNK_MESH = 0x10
CHUNK_COLORPALS = 0x11
# 0x12 is unused
# 0x13 is only nonzero for map000.5
# 0x14..0x18 is unused
CHUNK_LIGHTS = 0x19
CHUNK_TILES = 0x1a
CHUNK_TEX_ANIM = 0x1b
# is this rgba palettes or is it another texAnim set?
CHUNK_PAL_ANIM = 0x1c
# 0x1d is unused
# 0x1e is unused
CHUNK_GRAYPALS = 0x1f
# 0x20 is unused
# 0x21 is unused
# 0x22 is unused
# 0x23 is mesh animation info
# 0x24..0x2b = animated meshes 0-7
CHUNK_MESH_ANIM_BASE = 0x23
CHUNK_MESH_ANIM0 = 0x24
CHUNK_MESH_ANIM1 = 0x25
CHUNK_MESH_ANIM2 = 0x26
CHUNK_MESH_ANIM3 = 0x27
CHUNK_MESH_ANIM4 = 0x28
CHUNK_MESH_ANIM5 = 0x29
CHUNK_MESH_ANIM6 = 0x2a
CHUNK_MESH_ANIM7 = 0x2b
CHUNK_VISANGLES = 0x2c

# Header for non-texture resources
# Use this over just c_uint32 * 49 because this has endian-ness support
# Otherwise just (c_uint32 * 49) is easier to deal with (less indirections)
# But I don't see a way to specify endian-ness in ctypes of primitives or arrays of primitives
# Also, make this one field per uint32 (no arrays, etc) so that I can enumerate it like a uint32 array
# I would just make a struct of the whole thing being a single field of an array, just to get little-endian-ness
#  but meh, while here, why not name the fields too.
class ResHeaderFields(FFTStruct):
    _fields_ = [
        ('_00', c_uint32),
        ('_01', c_uint32),
        ('_02', c_uint32),
        ('_03', c_uint32),
        ('_04', c_uint32),
        ('_05', c_uint32),
        ('_06', c_uint32),
        ('_07', c_uint32),
        ('_08', c_uint32),
        ('_09', c_uint32),
        ('_0a', c_uint32),
        ('_0b', c_uint32),
        ('_0c', c_uint32),
        ('_0d', c_uint32),
        ('_0e', c_uint32),
        ('_0f', c_uint32),
        ('mesh', c_uint32),
        ('colorPals', c_uint32),
        ('_12', c_uint32),
        ('_13', c_uint32),
        ('_14', c_uint32),
        ('_15', c_uint32),
        ('_16', c_uint32),
        ('_17', c_uint32),
        ('_18', c_uint32),
        ('lights', c_uint32),
        ('tile', c_uint32),
        ('texAnim', c_uint32),
        ('palAnim', c_uint32),
        ('_1d', c_uint32),
        ('_1e', c_uint32),
        ('grayPals', c_uint32),
        ('_20', c_uint32),
        ('_21', c_uint32),
        ('_22', c_uint32),
        ('meshAnimBase', c_uint32),
        ('meshAnim0', c_uint32),
        ('meshAnim1', c_uint32),
        ('meshAnim2', c_uint32),
        ('meshAnim3', c_uint32),
        ('meshAnim4', c_uint32),
        ('meshAnim5', c_uint32),
        ('meshAnim6', c_uint32),
        ('meshAnim7', c_uint32),
        ('visAngles', c_uint32),
        ('_2d', c_uint32),
        ('_2e', c_uint32),
        ('_2f', c_uint32),
        ('_30', c_uint32),
    ]
assert sizeof(ResHeaderFields) == 4 * NUM_CHUNKS

# can't use unions in Blender until it upgrades to python 3.11
"""
class ResHeader(FFTUnion):
    _fields_ = [
        ('fields', ResHeaderFields),
        ('v', (c_uint32 * NUM_CHUNKS)),
    ]
assert sizeof(ResHeader) == 4 * NUM_CHUNKS
"""
# until then ...
class ResHeader(FFTStruct):
    _fields_ = [
        ('v', (c_uint32 * NUM_CHUNKS)),
    ]
assert sizeof(ResHeader) == 4 * NUM_CHUNKS


################################ non-texture resousre classes ################################

# very very very specific to the cmdline text outputter
#  still is a mess
class ToStr:
    @staticmethod
    def listToStr(o):
        s = []
        allPrim = True
        for v in o:
            allPrim &= isinstance(v, (int, str, bool))
            s.append(ToStr.toStr(v))
        sep=',\n'
        if allPrim:
            sep = ', '
        return '[\n'+sep.join(s)+'\n]'

    @staticmethod
    def toStr(o):
        if hasattr(o, '__iter__'):
            return ToStr.listToStr(o)
        # still can't figure out how to detect if an object is a ctype array, since it isn't iterable ...
        elif hasattr(o, '_length_') and hasattr(o, '_type_'):
            return ToStr.listToStr(list(o))
        else:
            return str(o)

    def __str__(self):
        s = []
        for (k, v) in vars(self).items():
            if k != 'data' and k != 'ofs':
                s.append(k+'='+ToStr.toStr(v))
        sep = ', '
        return '{'+sep.join(s)+'}'

class VertexTex(ToStr):
    def __init__(self, pos, normal, texcoord):
        self.pos = pos
        self.normal = normal
        self.texcoord = texcoord

class TriTex(ToStr):
    isTri = True
    isTex = True
    def __init__(self, points, normals, texFace, tilePos, visAngles):
        self.vtxs = [
            VertexTex(points[0], normals[0], texFace.uv0),
            VertexTex(points[1], normals[1], texFace.uv1),
            VertexTex(points[2], normals[2], texFace.uv2),
        ]
        self.texFace = texFace
        self.tilePos = tilePos
        self.visAngles = visAngles

class QuadTex(ToStr):
    isTri = False
    isTex = True
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

class VertexUntex(ToStr):
    def __init__(self, pos):
        self.pos = pos

class TriUntex(ToStr):
    isTri = True
    isTex = False
    def __init__(self, points, unknown, visAngles):
        self.vtxs = [
            VertexUntex(points[0]),
            VertexUntex(points[1]),
            VertexUntex(points[2]),
        ]
        self.unknown = unknown
        self.visAngles = visAngles

class QuadUntex(ToStr):
    isTri = False
    isTex = False
    def __init__(self, points, unknown, visAngles):
        self.vtxs = [
            VertexUntex(points[0]),
            VertexUntex(points[1]),
            VertexUntex(points[2]),
            VertexUntex(points[3]),
        ]
        self.unknown = unknown
        self.visAngles = visAngles

class Chunk(ToStr):
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

        # hold res here so toBin() can use it to access the meshChunk's blender objs later
        self.res = res

        # reading chunk 0x2c
        # from the 'writeVisAngles' function looks like this is written to a 1024 byte block always
        self.header = self.readBytes(0x380)
        self.triTexVisAngles = self.read(VisAngleFlags * 512)
        self.quadTexVisAngles = self.read(VisAngleFlags * 768)
        self.triUntexVisAngles = self.read(VisAngleFlags * 64)
        self.quadUntexVisAngles = self.read(VisAngleFlags * 256)
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
    def toBin(self):
        meshChunk = res.meshChunk
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
        self.triUntexUnknowns = self.read(UntexUnknown * self.hdr.numTriUntex) # then comes unknown 4 bytes per untex-tri
        self.quadUntexUnknowns = self.read(UntexUnknown * self.hdr.numQuadUntex) # then comes unknown 4 bytes per untex-quad
        #print('self.triUntexUnknowns', list(self.triUntexUnknowns))
        #print('self.quadUntexUnknowns', list(self.quadUntexUnknowns))

        self.triTexTilePos = self.read(TilePos * self.hdr.numTriTex) # then comes tile info 2 bytes per tex-tri
        self.quadTexTilePos = self.read(TilePos * self.hdr.numQuadTex) # then comes tile info 2 bytes per tex-quad
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
        self.pals = [self.read(RGBA5551 * 16) for i in range(16)]
        # done reading chunk

    def toBin(self):
        data = b''
        for colors in self.pals:
            data += bytes(colors)
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

    def toBin(self):
        return (
              bytes(self.dirLightColors)
            + bytes(self.dirLightDirs)
            + bytes(self.ambientLightColors)
            + bytes(self.backgroundColors)
            + self.footer
        )

class TileChunk(Chunk):
    def __init__(self, data, res):
        super().__init__(data)
        # reading chunk 0x1a
        self.sizeInTiles = self.read(c_uint8 * 2)  # (sizeX, sizeZ)
        # weird, it leaves room for 256 total tiles for the first xz plane, and then the second is packed?
        tileSrc = self.read(Tile * (256 + self.sizeInTiles[0] * self.sizeInTiles[1]))
        self.footer = self.readBytes()
        # done reading chunk 0x1a

        # convert the tiles from [z * sizeInTiles[0] + x] w/padding for y to [y][z][x]
        self.tiles = []
        for y in range(2):
            level = []
            for z in range(self.sizeInTiles[1]):
                row = []
                for x in range(self.sizeInTiles[0]):
                    row.append(tileSrc[256 * y + z * self.sizeInTiles[0] + x])
                level.append(row)
            self.tiles.append(level)

    def toBin(self):
        # TODO read this back from the blender mesh
        assert len(self.tiles) == 2
        self.sizeInTiles[0] = len(self.tiles[0][0])
        self.sizeInTiles[1] = len(self.tiles[0])
        data = bytes(self.sizeInTiles)
        for level in self.tiles:
            for row in level:
                for tile in row:
                    data += bytes(tile)
            # Skip to second level of tile data
            data += b'\0' * (sizeof(Tile) * (256 - sizeX * sizeZ))
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

def countSectors(size):
    return (size >> 11) + (1 if size & ((1<<11)-1) else 0)

class NonTexBlob(ResourceBlob):
    # specify which IO to use to read/associate with each chunk here
    # these can be overridden if the chunk has to do more work (ex: load Blender resources)
    chunkIOClasses = {
        CHUNK_MESH : MeshChunk,
        CHUNK_COLORPALS : ColorPalChunk,
        CHUNK_LIGHTS : LightChunk,
        CHUNK_TILES : TileChunk,
        CHUNK_TEX_ANIM : TexAnimChunk,
        #CHUNK_PAL_ANIM : PalAnimChunk,
        CHUNK_GRAYPALS : GrayPalChunk,
        CHUNK_VISANGLES : VisAngleChunk,
    }

    def __init__(self, record, filename, mapdir, gns):
        super().__init__(record, filename, mapdir)
        data = self.readData()
        self.numSectors = countSectors(len(data))

        # store here just for chunks to use.  I could pass it through to chunks individually , but , meh...
        self.gns = gns

        self.header = ResHeader.from_buffer_copy(data)

        chunks = [None] * NUM_CHUNKS
        for i, entry in enumerate(self.header.v):
            begin = self.header.v[i]
            if begin:
                end = None
                for j in range(i + 1, NUM_CHUNKS):
                    if self.header.v[j]:
                        end = self.header.v[j]
                        break
                if end == None:
                    end = len(data)
                chunks[i] = data[begin:end]

        # each chunk's IO
        self.chunkIOs = [None] * NUM_CHUNKS

        # if the chunk was in the header, read it with its respective class
        # store it in chunkIOs, but also in its respective field
        # (the outside world can reference the named fields)
        def readChunk(i):
            nonlocal chunks
            data = chunks[i]
            if data:
                if not i in self.chunkIOClasses:
                    print("WARNING: resource has chunk "+str(i)+" but I don't have a class for reading it")
                else:
                    cl = self.chunkIOClasses[i]
                    io = cl(data, self)
                    self.chunkIOs[i] = io
                    return io

        self.visAngleChunk = readChunk(CHUNK_VISANGLES)     # needs to be read before meshChunk
        self.meshChunk = readChunk(CHUNK_MESH)              # needs to be read after visAngleChunk
        self.colorPalChunk = readChunk(CHUNK_COLORPALS)
        self.lightChunk = readChunk(CHUNK_LIGHTS)           # this needs bbox if it exists, which is calculated in meshChunk's ctor
        self.tileChunk = readChunk(CHUNK_TILES)
        self.texAnimChunk = readChunk(CHUNK_TEX_ANIM)
        self.palAnimChunk = readChunk(CHUNK_PAL_ANIM)
        self.grayPalChunk = readChunk(CHUNK_GRAYPALS)

    def write(self):
        chunks = [None] * NUM_CHUNKS
        for i in range(NUM_CHUNKS):
            if (i, io) in enumerate(self.chunkIOs):
                if io != None:
                    chunks[i] = io.toBin()

        # now write the header
        ofs = sizeof(self.header.v)
        for (i, chunk) in enumerate(chunks):
            if chunk:
                self.header.v[i] = ofs
                ofs += len(chunk)
            else:
                self.header.v[i] = 0
        data = bytes(self.header.v)
        for chunk in chunks:
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

################################ the GNS file ################################

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

        # always 0 on all maps
        ('_03', c_uint8, 4),

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
        # 0x31 = EOF (and the struct might be truncated after 8 bytes)
        #
        # ... I don't see where these appear in the wild:
        # 0x80 0x85 0x86 0x87 0x88 = also listed in GaneshaDx
        ('resourceType', c_uint8),

        # trails GNSRecord if it isn't a RESOURCE_EOF
        # do I really need to break these into two separate reads?
        # I think GaneshaDx puts a threshold of 20 bytes ... meaning we shoudl always be able to access both structs...

        # always 0x3333
        ('_06', c_uint16),

        # disk sector
        ('sector', c_uint32),

        # file size, rounded up to 2k block
        # sector plus roundup(size/2k) = next sector
        # but is there a relation between the file ext no? both are sequential in same order.  neither are 1:1 with indexes
        ('size', c_uint32),

        # always 0x88776655
        ('_0a', c_uint32),
    ]

    # return the tuple of arrangement, isNight, weather which are used to uniquely identify ... bleh
    def getMapState(self):
        return (self.arrangement, self.isNight, self.weather)

    # GaneshaDx: texture resources:
    RESOURCE_TEXTURE = 0x17

    # GaneshaDx: mesh resources:
    # this is the init mesh, looks like it is always used unless overridden ...
    RESOURCE_MESH_INIT = 0x2e # Always used with (0x22, 0, 0, 0). Always a big file.

    # ... this is the override
    # screenshot from ... ? shows RESOURCE_REPL with prim mesh, pal, lights, tiles, tex.anim., and pal.anim.
    RESOURCE_MESH_REPL = 0x2f # Always used with (0x30, 0, 0, 0). Usually a big file.

    # this is just pal and lights
    RESOURCE_MESH_ALT = 0x30 # Used with many index combos. Usually a small file.

    # GaneshaDx: other stuff I guess
    RESOURCE_EOF = 0x31       # GaneshaDx calls this one "Padded" ... as in file-padding?  as in EOF record?

    RESOURCE_UNKNOWN_EXTRA_DATA_A = 0x80 # from GaneshaDx
    RESOURCE_UNKNOWN_TWIN_1 = 0x85
    RESOURCE_UNKNOWN_TWIN_2 = 0x86
    RESOURCE_UNKNOWN_TWIN_3 = 0x87
    RESOURCE_UNKNOWN_TWIN_4 = 0x88

assert sizeof(GNSRecord) == 20


# read the GNS records ... which are 20 bytes, or 8 bytes for the EOF
# read the files in the same dir
# make a 1:1 mapping between them
# sort out which files are texture vs non-texture resources
# collects all used mapstates in 'allMapStates'
class GNS(object):
    # allow overloading
    TexBlob = TexBlob
    NonTexBlob = NonTexBlob

    def __init__(self, filepath):
        self.filepath = filepath
        self.mapdir = os.path.dirname(filepath)
        self.filename = os.path.basename(filepath)
        self.nameroot = os.path.splitext(self.filename)[0]

        print(filepath, os.path.getsize(filepath))

        file = open(self.filepath, 'rb')
        self.allRecords = []
        while True:
            #def readStruct(file, struct):
            #    return struct.from_buffer_copy(file.read(sizeof(struct)))
            #r = readStruct(file, GNSRecord)
            # but it could be incomplete right?
            # file.read(numBytes) will fail gracefully
            # but I think ctype.from_buffer_copy won't ...
            sdata = file.read(sizeof(GNSRecord))
            # TODO when is sdata not long enough?  only in the case of RESOURCE_EOF? always in that case?
            # TODO must GNS be aligned to something?
            sdata = sdata + b'\0' * (sizeof(GNSRecord) - len(sdata)) # pad?
            r = GNSRecord.from_buffer_copy(sdata)
            if r.resourceFlag == 1 and r.resourceType == GNSRecord.RESOURCE_EOF:
                break
            self.allRecords.append(r)
        file.close()

        self.allRecords.sort(key=lambda a: a.sector)

        # now using sorted sectors and file suffixes, map all records to their files
        allSectors = sorted(set(r.sector for r in self.allRecords))

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
        #print(allResFilenames)

        # enumerate unique (arrangement,night,weather) tuples
        # sort them too, so the first one is our (0,0,0) initial state
        self.allMapStates = sorted(set(r.getMapState() for r in self.allRecords))
        #print('all map states:')
        #print('arrangement / night / weather:')
        #for s in self.allMapStates:
        #    print(s)

        # now, here, per resource file, load *everything* you can
        # I'm gonna put everything inside blender first and then sort it out per-scene later

        self.allRes = []
        self.allTexRes = []
        self.allMeshRes = []
        for (i, r) in enumerate(self.allRecords):
            #print('record', self.filenameForSector[r.sector], str(r), end='')
            res = None
            if r.resourceType == r.RESOURCE_TEXTURE:
                #print('...tex')
                res = self.TexBlob(
                    r,
                    self.filenameForSector[r.sector],
                    self.mapdir
                )
                self.allTexRes.append(res)
            elif (r.resourceType == r.RESOURCE_MESH_INIT
                or r.resourceType == r.RESOURCE_MESH_REPL
                or r.resourceType == r.RESOURCE_MESH_ALT):
                res = self.NonTexBlob(
                    r,
                    self.filenameForSector[r.sector],
                    self.mapdir,
                    self
                )
                #print('...res w/chunks '+str([i for i, e in enumerate(res.header.v) if e != 0]))
                self.allMeshRes.append(res)
            else:
                res = self.UnknownBlob(r, self.filenameForSector[r.sector], self.mapdir, self)
            self.allRes.append(res)
            # else keep it anywhere?
        assert len(self.allRes) == len(self.allRecords)

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
            'tileChunk'
        ]:
            setResField(field)
 

