import math
import os.path
import bpy
from bpy_extras import node_shader_utils
from ctypes import *

################################ ctypes ################################

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
        # 0x31 = EOF (and the struct might be truncated after 8 bytes)
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

# GaneshaDx: texture resources:
GNSRecord.RESOURCE_TEXTURE = 0x17

# GaneshaDx: mesh resources:
# this is the init mesh, looks like it is always used unless overridden ...
GNSRecord.RESOURCE_MESH_INIT = 0x2e # Always used with (0x22, 0, 0, 0). Always a big file.

# ... this is the override
# screenshot from ... ? shows RESOURCE_REPL with prim mesh, pal, lights, terrain, tex.anim., and pal.anim.
GNSRecord.RESOURCE_MESH_REPL = 0x2f # Always used with (0x30, 0, 0, 0). Usually a big file.

# this is just pal and lights
GNSRecord.RESOURCE_MESH_ALT = 0x30 # Used with many index combos. Usually a small file.

# GaneshaDx: other stuff I guess
GNSRecord.RESOURCE_EOF = 0x31       # GaneshaDx calls this one "Padded" ... as in file-padding?  as in EOF record?

GNSRecord.RESOURCE_UNKNOWN_EXTRA_DATA_A = 0x80 # from GaneshaDx

GNSRecord.RESOURCE_UNKNOWN_TWIN_1 = 0x85

GNSRecord.RESOURCE_UNKNOWN_TWIN_2 = 0x86

GNSRecord.RESOURCE_UNKNOWN_TWIN_3 = 0x87

GNSRecord.RESOURCE_UNKNOWN_TWIN_4 = 0x88

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




# read the GNS records ... which are 20 bytes, or 8 bytes for the EOF
# read the files in the same dir
# make a 1:1 mapping between them
# sort out which files are texture vs non-texture resources
class GNS(object):
    def __init__(self, filepath):
        mapdir = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        nameroot = os.path.splitext(filename)[0]

        print(filepath, os.path.getsize(filepath))
        file = open(filepath, 'rb')
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
        for fn in os.listdir(mapdir):
            if fn != filename and os.path.splitext(fn)[0] == nameroot:
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

        # enumerate unique (arrangement,night,weather) tuples
        # sort them too, so the first one is our (0,0,0) initial state
        self.allMapStates = sorted(set(r.getMapState() for r in self.allRecords))
        #print('all map states:')
        #print('arrangement / night / weather:')
        #for s in self.allMapStates:
        #    print(s)

################################ classes ################################

class VertexTex(object):
    def __init__(self, pos, normal, texcoord):
        self.pos = pos
        self.normal = normal
        self.texcoord = texcoord

class TriTex(object):
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

class QuadTex(object):
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


class VertexUntex(object):
    def __init__(self, pos):
        self.pos = pos

class TriUntex(object):
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

class QuadUntex(object):
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
        
        # hold res here so toBin() can use it to access the meshChunk's blender objs later
        self.res = res

        # reading chunk 0x2c
        # from the 'writeVisAngles' function looks like this is written to a 1024 byte block always
        self.header = self.readBytes(0x380)
        # TODO how to associate endian-ness with a primitive type?
        self.triTexVisAngles = self.read(c_uint16 * 512)
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
        # TODO how to associate endian-ness with a primitive type?
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

def countSectors(size):
    return (size >> 11) + (1 if size & ((1<<11)-1) else 0)

class NonTexBlob(ResourceBlob):
    
    # chunks used in maps 001 thru 119:
    # in hex: 10, 11, 13, 19, 1a, 1b, 1c, 1f, 23, 24, 25, 26, 27, 28, 29, 2a, 2b, 2c
    # missing:
    # in hex: 12, 14, 15, 16, 17, 18, 1d, 1e, 20, 21, 22
    # ... seems like the first 64 bytes are used for something else
    numChunks = 49

    # specify which IO to use to read/associate with each chunk here
    # these can be overridden if the chunk has to do more work (ex: load Blender resources) 
    chunkIOClasses = {
        0x10 = MeshChunk,
        0x11 = ColorPalChunk,
        # 0x12 is unused
        # 0x13 is only nonzero for map000.5
        # 0x14..0x18 is unused
        0x19 = LightChunk,
        0x1a = TerrainChunk,
        0x1b = TexAnimChunk,
        # is this rgba palettes or is it another texAnim set?
        #0x1c = PalAnimChunk,
        # 0x1d is unused
        # 0x1e is unused
        0x1f = GrayPalChunk,
        # 0x20 is unused
        # 0x21 is unused
        # 0x22 is unused
        # 0x23 is mesh animation info
        # 0x24..0x2b = animated meshes 0-7
        0x2c = VisAngleChunk,
    }
    
    def __init__(self, record, filename, mapdir, gns):
        super().__init__(record, filename, mapdir)
        data = self.readData()
        self.numSectors = countSectors(len(data))

        # store here just for chunks to use.  I could pass it through to chunks individually , but , meh...
        self.gns = gns

        # TODO how does ctypes associate endian-ness with a primitive type?
        self.header = (c_uint32 * self.numChunks).from_buffer_copy(data)

        chunks = [None] * self.numChunks
        for i, entry in enumerate(self.header):
            begin = self.header[i]
            if begin:
                end = None
                for j in range(i + 1, self.numChunks):
                    if self.header[j]:
                        end = self.header[j]
                        break
                if end == None:
                    end = len(data)
                chunks[i] = data[begin:end]

        # each chunk's IO
        self.chunkIOs = {}

        # if the chunk was in the header, read it with its respective class
        # store it in chunkIOs, but also in its respective field
        # (the outside world can reference the named fields)
        def readChunk(i):
            nonlocal chunk
            data = chunks[i]
            if data:
                if not i in self.chunkIOClasses:
                    print("WARNING: resource has chunk "+str(i)+" but we don't have a class for reading it")
                else:
                    cl = self.chunkIOClasses[i]
                    return self.chunkIOs[i] = cl(data, self)

        self.visAngleChunk = readChunk(0x2c)    # needs to be read before meshChunk
        self.meshChunk = readChunk(0x10)        # needs to be read after visAngleChunk
        self.colorPalChunk = readChunk(0x11)
        self.lightChunk = readChunk(0x19)       # this needs bbox if it exists, which is calculated in meshChunk's ctor
        self.terrainChunk = readChunk(0x1a)
        self.texAnimChunk = readChunk(0x1b)
        self.palAnimChunk = readChunk(0x1c)
        self.grayPalChunk = readChunk(0x1f)

    def write(self):
        chunks = [None] * self.numChunks
        for i in range(numChunks):
            if i in self.chunkIOs:
                io = self.chunkIOs[i]
                if io != None:
                    chunks[i] = io.toBin()
        
        # now write the header
        ofs = sizeof(self.header)
        for (i, chunk) in enumerate(chunks):
            if chunk:
                self.header[i] = ofs
                ofs += len(chunk)
            else:
                self.header[i] = 0
        data = bytes(self.header)
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


