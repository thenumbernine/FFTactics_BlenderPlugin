# https://ffhacktics.com/wiki/Maps/Mesh

import array
import os
import time
import bpy
import math
import mathutils

from bpy_extras.io_utils import unpack_list
from bpy_extras.image_utils import load_image
from bpy_extras.wm_utils.progress_report import ProgressReport

################################ all the ganesha imports ################################

import os, sys, struct
import os.path
from os.path import getsize
from struct import pack, unpack
from datetime import datetime

from ctypes import *

class MyStruct(Structure):
    # why isn't there an eays wya to do this?
    def toTuple(self):
        return tuple(getattr(self, x[0]) for x in self._fields_)

class Situation(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('index1', c_uint16),
        ('arrange', c_uint8),
        ('temp1', c_uint8, 4),
        ('weather', c_uint8, 3),
        ('time', c_uint8, 1),    # day vs night?
        ('resourceType', c_uint16),
    ]

# trails Situation if it isn't a RESOURCE_EOF
class SituationEx(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('unused00', c_uint16),
        ('lba', c_uint32),
        ('size', c_uint32),
        ('unused0A', c_uint32),
    ]

# aka VertexPos
class short3_t(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('x', c_int16),
        ('y', c_int16),
        ('z', c_int16),
    ]

class Normal(MyStruct):
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

# aka texcoord...
class ubyte2_t(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('x', c_uint8),
        ('y', c_uint8),
    ]

# textured-triangle face information
class TriTexFace(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('uv0', ubyte2_t),
        ('pal', c_uint8, 4),
        ('unk2_4', c_uint8, 4),
        ('unk3', c_uint8),
        ('uv1', ubyte2_t),
        ('page', c_uint8, 2),
        ('unk6_2', c_uint8, 6),
        ('unk7', c_uint8),
        ('uv2', ubyte2_t),
    ]
assert(sizeof(TriTexFace) == 10)

# textured-quad face information
# matches TriTexFace
class QuadTexFace(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('uv0', ubyte2_t),
        ('pal', c_uint8, 4),
        ('unk2_4', c_uint8, 4),
        ('unk3', c_uint8),
        ('uv1', ubyte2_t),
        ('page', c_uint8, 2),
        ('unk6_2', c_uint8, 6),
        ('unk7', c_uint8),
        ('uv2', ubyte2_t),
        ('uv3', ubyte2_t),
    ]
assert(sizeof(QuadTexFace) == 12)

# tile in-game position, stored per-textured-face
class TilePos(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('x', c_uint8),
        ('y', c_uint8, 1),
        ('z', c_uint8, 7),
    ]
assert(sizeof(TilePos) == 2)

class RGBA5551(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('r', c_ushort, 5),
        ('g', c_ushort, 5),
        ('b', c_ushort, 5),
        ('a', c_ushort, 1)
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

class MeshHeader(MyStruct):
    _pack_ = 1
    _fields_ = [
        ('numTriTex', c_uint16),
        ('numQuadTex', c_uint16),
        ('numTriUntex', c_uint16),
        ('numQuadUntex', c_uint16),
    ]

def readStruct(file, struct):
    return struct.from_buffer_copy(file.read(sizeof(struct)))

################################ fft/map/texture.py ################################

class Texture_File(object):
    def __init__(self):
        self.file_path = None
        self.file = None
        self.data = None

    def read(self, files):
        for file_path in files:
            self.file_path = file_path
            self.file = open(self.file_path, 'rb')
            self.data = self.file.read()
            break
        print('tex', self.file_path)
        self.file.close()

    def write(self, data):
        self.file = open(self.file_path, 'wb')
        print('Writing', self.file_path)
        self.file.write(data)
        self.file.close()

################################ fft/map/resource.py ################################

# this holds the TOC list of int32 offsets per ... resource?
# why is there Resource.chunks and Resources.chunks?  when they are assigned the same thing?
class Resource(object):
    def __init__(self):
        super(Resource, self).__init__()
        self.file_path = None
        self.file = None
        self.chunks = [''] * 49
        self.size = None

    # check.
    def read(self, file_path):
        self.file_path = file_path
        self.size = getsize(self.file_path)
        self.file = open(self.file_path, 'rb')
        toc = list(unpack('<49I', self.file.read(0xc4)))
        self.file.seek(0)
        data = self.file.read()
        self.file.close()
        toc.append(self.size)
        for i, entry in enumerate(toc[:-1]):
            begin = toc[i]
            if begin == 0:
                print(file_path, i, 'resource offset is zero ... skipping')
                continue
            end = None
            for j in range(i + 1, len(toc)):
                if toc[j]:
                    end = toc[j]
                    break
            self.chunks[i] = data[begin:end]
            print(i, self.file_path, begin, end)
        self.toc = toc

    def write(self):
        offset = 0xc4
        toc = []
        for chunk in self.chunks:
            if chunk:
                toc.append(offset)
                offset += len(chunk)
            else:
                toc.append(0)
        data = pack('<49I', *toc)
        for chunk in self.chunks:
            data += chunk
        print('Writing', self.file_path)
        dateTime = datetime.now()
        print(dateTime)
        old_size = self.size
        self.size = len(data)
        countSectors = lambda size: (size >> 11) + (1 if size & ((1<<11)-1) else 0)
        old_sectors = countSectors(old_size)
        new_sectors = countSectors(self.size)
        if new_sectors > old_sectors:
            print('WARNING: File has grown from %u sectors to %u sectors!' % (old_sectors, new_sectors))
        elif new_sectors < old_sectors:
            print('Note: File has shrunk from %u sectors to %u sectors.' % (old_sectors, new_sectors))
        self.file = open(self.file_path, 'wb')
        self.file.write(data)
        self.file.close()


class Resources(object):
    def __init__(self):
        super(Resources, self).__init__()
        self.chunks = [None] * 49

    # check.
    def read(self, files):
        for file_path in files:
            resource = Resource()
            resource.read(file_path)
            for i in range(49):
                if self.chunks[i] is not None:
                    continue
                if resource.chunks[i]:
                    print('setting chunk', i, 'to', file_path)
                    self.chunks[i] = resource

    # check.
    def get_tex_3gon_xyz(self, hdr, data):
        offset = 8
        for i in range(hdr.numTriTex):
            yield data[offset:offset+18]
            offset += 18

    # check.
    def get_tex_4gon_xyz(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18
        for i in range(hdr.numQuadTex):
            yield data[offset:offset+24]
            offset += 24

    # check.
    def get_untex_3gon_xyz(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24
        for i in range(hdr.numTriUntex):
            yield data[offset:offset+18]
            offset += 18

    # check.
    def get_untex_4gon_xyz(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18
        for i in range(hdr.numQuadUntex):
            yield data[offset:offset+24]
            offset += 24

    # check.
    def get_tex_3gon_norm(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24
        for i in range(hdr.numTriTex):
            yield data[offset:offset+18]
            offset += 18

    # check.
    def get_tex_4gon_norm(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18
        for i in range(hdr.numQuadTex):
            yield data[offset:offset+24]
            offset += 24

    # check.
    def get_tex_3gon_uv(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18 + hdr.numQuadTex * 24
        for i in range(hdr.numTriTex):
            texcoordData = data[offset:offset+10]
            yield texcoordData
            offset += 10

    # check.
    def get_tex_4gon_uv(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriTex * 10
        for i in range(hdr.numQuadTex):
            texcoordData = data[offset:offset+12]
            yield texcoordData
            offset += 12

    # check.
    def get_untex_3gon_unknown(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriTex * 10 + hdr.numQuadTex * 12
        for i in range(hdr.numTriUntex):
            yield data[offset:offset+4]
            offset += 4

    # check.
    def get_untex_4gon_unknown(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriTex * 10 + hdr.numQuadTex * 12 + hdr.numTriUntex * 4
        for i in range(hdr.numQuadUntex):
            yield data[offset:offset+4]
            offset += 4

    # check.
    def get_tex_3gon_terrain_coords(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriTex * 10 + hdr.numQuadTex * 12 + hdr.numTriUntex * 4 + hdr.numQuadUntex * 4
        for i in range(hdr.numTriTex):
            terrainCoordData = data[offset:offset+2]
            yield terrainCoordData
            offset += 2

    # check.
    def get_tex_4gon_terrain_coords(self, hdr, data):
        offset = 8 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriUntex * 18 + hdr.numQuadUntex * 24 + hdr.numTriTex * 18 + hdr.numQuadTex * 24 + hdr.numTriTex * 10 + hdr.numQuadTex * 12 + hdr.numTriUntex * 4 + hdr.numQuadUntex * 4 + hdr.numTriTex * 2
        for i in range(hdr.numQuadTex):
            terrainCoordData = data[offset:offset+2]
            yield terrainCoordData
            offset += 2

    # check.
    def get_tex_3gon_vis(self):
        resource = self.chunks[0x2c]
        data = resource.chunks[0x2c]
        offset = 0x380
        for i in range(512):
            yield data[offset:offset+2]
            offset += 2

    # check.
    def get_tex_4gon_vis(self):
        resource = self.chunks[0x2c]
        data = resource.chunks[0x2c]
        offset = 0x380 + 512 * 2
        for i in range(768):
            yield data[offset:offset+2]
            offset += 2

    # check.
    def get_untex_3gon_vis(self):
        resource = self.chunks[0x2c]
        data = resource.chunks[0x2c]
        offset = 0x380 + 512 * 2 + 768 * 2
        for i in range(64):
            yield data[offset:offset+2]
            offset += 2

    # check.
    def get_untex_4gon_vis(self):
        resource = self.chunks[0x2c]
        data = resource.chunks[0x2c]
        offset = 0x380 + 512 * 2 + 768 * 2 + 64 * 2
        for i in range(256):
            yield data[offset:offset+2]
            offset += 2

    # check.
    def get_color_palettes(self):
        resource = self.chunks[0x11]
        data = resource.chunks[0x11]
        ofs = 0
        for i in range(16):
            yield data[ofs:ofs+32]
            ofs += 32

    # struct fixed16_t { uint16_t ipart : 4; uint16_t fpart : 12 };
    # struct { fixed16_t red[3], green[3], blue[3] }
    def get_dir_light_rgb(self):
        resource = self.chunks[0x19]
        data = resource.chunks[0x19]
        atou16 = lambda data: unpack('<H', data)[0]
        ofs = 0
        for i in range(3):
            # GaneshaDx says read signed (?) int16, clamp the value to 2040 (2048?), then divide by 8 to get [0,255]
            # so that means the bottom 11 bits are color channels
            # then what are the top 5 bits?
            mask = (1<<11)-1
            yield (
                (atou16(data[ofs:ofs+2]) & mask) / float(mask),
                (atou16(data[ofs+6:ofs+8]) & mask) / float(mask),
                (atou16(data[ofs+12:ofs+14]) & mask) / float(mask)
            )
            ofs += 2

    # struct{ short x,y,z }[3];
    def get_dir_light_norm(self):
        resource = self.chunks[0x19]
        data = resource.chunks[0x19]
        ofs = 18
        for i in range(3):
            yield unpack('<3h', data[ofs:ofs+6])
            ofs += 6

    # struct color_t { byte r,g,b };
    # color_t color
    def get_amb_light_rgb(self):
        resource = self.chunks[0x19]
        data = resource.chunks[0x19]
        offset = 36
        return [x/255. for x in unpack('<3B', data[offset:offset+3])]

    # struct { color_t top, bottom };
    def get_background(self):
        resource = self.chunks[0x19]
        data = resource.chunks[0x19]
        offset = 39
        return [
            unpack('<3B', data[offset:offset+3]),
            unpack('<3B', data[offset+3:offset+6])
        ]

    # TODO
    def get_terrain(self):
        resource = self.chunks[0x1a]
        data = resource.chunks[0x1a]
        offset = 0
        return data

    # check.
    def get_gray_palettes(self):
        resource = self.chunks[0x1f]
        data = resource.chunks[0x1f]
        offset = 0
        for i in range(16):
            yield data[offset:offset+32]
            offset += 32

    def write(self):
        written = []
        for chunk in self.chunks:
            if chunk and chunk.file_path not in written:
                chunk.write()
                written.append(chunk.file_path)

    def put_polygons(self, polygons, toc_offset=0x40):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 0
        tex_tri = []
        tex_quad = []
        untex_tri = []
        untex_quad = []
        for polygon in polygons:
            if hasattr(polygon.source, 'D') and polygon.source.A.normal:
                tex_quad.append(polygon.source)
            elif hasattr(polygon.source, 'D') and not polygon.source.A.normal:
                untex_quad.append(polygon.source)
            elif polygon.source.A.normal:
                tex_tri.append(polygon.source)
            else:
                untex_tri.append(polygon.source)
        polygons_data = pack('<4H', *[len(x) for x in [tex_tri, tex_quad, untex_tri, untex_quad]])
        for polygon in tex_tri:
            for abc in ['A', 'B', 'C']:
                polygons_data += pack('<3h', *getattr(polygon, abc).point)
        for polygon in tex_quad:
            for abc in ['A', 'B', 'C', 'D']:
                polygons_data += pack('<3h', *getattr(polygon, abc).point)
        for polygon in untex_tri:
            for abc in ['A', 'B', 'C']:
                polygons_data += pack('<3h', *getattr(polygon, abc).point)
        for polygon in untex_quad:
            for abc in ['A', 'B', 'C', 'D']:
                polygons_data += pack('<3h', *getattr(polygon, abc).point)
        for polygon in tex_tri:
            for abc in ['A', 'B', 'C']:
                polygons_data += pack('<3h', *[int(x * 4096.) for x in getattr(polygon, abc).normal])
        for polygon in tex_quad:
            for abc in ['A', 'B', 'C', 'D']:
                polygons_data += pack('<3h', *[int(x * 4096.) for x in getattr(polygon, abc).normal])
        for polygon in tex_tri:
            if polygon.unknown3 == 0:
                polygon.unknown3 = 120
                polygon.unknown6_2 = 3
            polygons_data += (''
                + pack('BB', *polygon.A.texcoord)
                + pack('BB', *[(polygon.unknown2_4 << 4) | polygon.paletteIndex, polygon.unknown3])
                + pack('BB', *polygon.B.texcoord)
                + pack('BB', *[(polygon.unknown6_2 << 2) | polygon.texturePage, polygon.unknown4])
                + pack('BB', *polygon.C.texcoord)
            )
        for polygon in tex_quad:
            if polygon.unknown3 == 0:
                polygon.unknown3 = 120
                polygon.unknown6_2 = 3
            polygons_data += (''
                + pack('BB', *polygon.A.texcoord)
                + pack('BB', *[(polygon.unknown2_4 << 4) + polygon.paletteIndex, polygon.unknown3])
                + pack('BB', *polygon.B.texcoord)
                + pack('BB', *[(polygon.unknown6_2 << 2) + polygon.texturePage, polygon.unknown4])
                + pack('BB', *polygon.C.texcoord)
                + pack('BB', *polygon.D.texcoord)
            )
        for polygon in untex_tri:
            polygons_data += polygon.unknown5
        for polygon in untex_quad:
            polygons_data += polygon.unknown5
        for polygon in tex_tri:
            val1 = (polygon.terrainCoords[1] << 1) + polygon.terrainCoords[2]
            polygons_data += pack('BB', val1, polygon.terrainCoords[0])
        for polygon in tex_quad:
            val1 = (polygon.terrainCoords[1] << 1) + polygon.terrainCoords[2]
            polygons_data += pack('BB', val1, polygon.terrainCoords[0])
        resource.chunks[toc_offset >> 2] = polygons_data

    def put_palettes(self, palettes, toc_offset=0x44):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 0
        palette_data = ''
        for palette in palettes:
            for c in range(16):
                (r, g, b, a) = palette[c]
                value = a << 15
                value |= b << 10
                value |= g << 5
                value |= r << 0
                palette_data += pack('<H', value)
        resource.chunks[toc_offset >> 2] = palette_data

    def put_dir_lights(self, dir_lights, toc_offset=0x64):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 0
        light_data = ''
        for color in range(3):
            for light in dir_lights:
                light_data += pack('<h', light.color[color])
        for light in dir_lights:
            for dim in range(3):
                light_data += pack('<h', int(4096.0 * light.direction.coords[dim]))
        resource.chunks[toc_offset >> 2] = data[:offset] + light_data + data[offset + 36:]

    def put_amb_light_rgb(self, light_data, toc_offset=0x64):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 36
        resource.chunks[toc_offset >> 2] = data[:offset] + light_data + data[offset + 3:]

    def put_background(self, background_data, toc_offset=0x64):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 39
        resource.chunks[toc_offset >> 2] = data[:offset] + background_data + data[offset + 6:]

    def put_terrain(self, terrainData, toc_offset=0x68):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 0
        resource.chunks[toc_offset >> 2] = data[:offset] + terrainData + data[offset + len(terrainData):]

    def put_visible_angles(self, polygons, toc_offset=0xb0):
        resource = self.chunks[toc_offset >> 2]
        data = resource.chunks[toc_offset >> 2]
        offset = 0x380
        tex_tri = []
        tex_quad = []
        untex_tri = []
        untex_quad = []
        for polygon in polygons:
            if hasattr(polygon.source, 'D') and polygon.source.A.normal:
                tex_quad.append(polygon.source)
            elif hasattr(polygon.source, 'D') and not polygon.source.A.normal:
                untex_quad.append(polygon.source)
            elif polygon.source.A.normal:
                tex_tri.append(polygon.source)
            else:
                untex_tri.append(polygon.source)
        tex_tri_data = ''
        tex_quad_data = ''
        untex_tri_data = ''
        untex_quad_data = ''
        for polygon in tex_tri:
            vis = sum([ x << (15-i) for i, x in enumerate(polygon.visible_angles) ])
            tex_tri_data += pack('<H', vis)
        tex_tri_data += '\x00' * (1024 - len(tex_tri_data))
        for polygon in tex_quad:
            vis = sum([ x << (15-i) for i, x in enumerate(polygon.visible_angles) ])
            tex_quad_data += pack('<H', vis)
        tex_quad_data += '\x00' * (1536 - len(tex_quad_data))
        for polygon in untex_tri:
            vis = sum([ x << (15-i) for i, x in enumerate(polygon.visible_angles) ])
            untex_tri_data += pack('<H', vis)
        untex_tri_data += '\x00' * (128 - len(untex_tri_data))
        for polygon in untex_quad:
            vis = sum([ x << (15-i) for i, x in enumerate(polygon.visible_angles) ])
            untex_quad_data += pack('<H', vis)
        untex_quad_data += '\x00' * (512 - len(untex_quad_data))
        visible_angles_data = tex_tri_data + tex_quad_data + untex_tri_data + untex_quad_data
        resource.chunks[toc_offset >> 2] = data[:offset] + visible_angles_data + data[offset + len(visible_angles_data):]

################################ fft/map/gns.py ################################

INDEX1_22 = 0x22
INDEX1_30 = 0x30
INDEX1_70 = 0x70
ARRANGE_0 = 0x0
ARRANGE_1 = 0x1
ARRANGE_2 = 0x2
ARRANGE_3 = 0x3
ARRANGE_4 = 0x4
ARRANGE_5 = 0x5
TIME_0 = 0x0
TIME_1 = 0x1
WEATHER_0 = 0x0
WEATHER_1 = 0x1
WEATHER_2 = 0x2
WEATHER_3 = 0x3
WEATHER_4 = 0x4
DEFAULT_INDEX = (INDEX1_22, ARRANGE_0, TIME_0, WEATHER_0)

RESOURCE_TEXTURE = 0x1701
RESOURCE_TYPE0 = 0x2e01 # Always used with (0x22, 0, 0, 0). Always a big file.
RESOURCE_TYPE1 = 0x2f01 # Always used with (0x30, 0, 0, 0). Usually a big file.
RESOURCE_TYPE2 = 0x3001 # Used with many index combos. Usually a small file.
RESOURCE_EOF = 0x3101

gnslines = {
        (0, 0): 'MAP000.5',
        (1, 0): 'MAP001.8',
        (1, 1): 'MAP001.9',
        (1, 2): 'MAP001.11',
        (1, 3): 'MAP001.14',
        (1, 4): 'MAP001.15',
        (1, 5): 'MAP001.18',
        (1, 6): 'MAP001.19',
        (1, 7): 'MAP001.22',
        (1, 8): 'MAP001.23',
        (1, 9): 'MAP001.26',
        (1, 10): 'MAP001.27',
        (1, 11): 'MAP001.30',
        (1, 12): 'MAP001.31',
        (1, 13): 'MAP001.34',
        (1, 14): 'MAP001.35',
        (1, 15): 'MAP001.38',
        (1, 16): 'MAP001.39',
        (1, 17): 'MAP001.42',
        (1, 18): 'MAP001.43',
        (1, 19): 'MAP001.46',
        (1, 20): 'MAP001.47',
        (1, 21): 'MAP001.48',
        (1, 22): 'MAP001.52',
        (1, 23): 'MAP001.53',
        (1, 24): 'MAP001.57',
        (1, 25): 'MAP001.58',
        (1, 26): 'MAP001.62',
        (1, 27): 'MAP001.63',
        (1, 28): 'MAP001.67',
        (1, 29): 'MAP001.68',
        (1, 30): 'MAP001.72',
        (1, 31): 'MAP001.73',
        (1, 32): 'MAP001.77',
        (1, 33): 'MAP001.78',
        (1, 34): 'MAP001.82',
        (1, 35): 'MAP001.83',
        (1, 36): 'MAP001.87',
        (1, 37): 'MAP001.88',
        (1, 38): 'MAP001.92',
        (1, 39): 'MAP001.93',
        (2, 0): 'MAP002.8',
        (2, 1): 'MAP002.9',
        (2, 2): 'MAP002.12',
        (2, 3): 'MAP002.13',
        (2, 4): 'MAP002.16',
        (2, 5): 'MAP002.17',
        (2, 6): 'MAP002.20',
        (2, 7): 'MAP002.21',
        (2, 8): 'MAP002.24',
        (2, 9): 'MAP002.25',
        (2, 10): 'MAP002.28',
        (2, 11): 'MAP002.29',
        (2, 12): 'MAP002.32',
        (2, 13): 'MAP002.33',
        (2, 14): 'MAP002.36',
        (2, 15): 'MAP002.37',
        (2, 16): 'MAP002.40',
        (2, 17): 'MAP002.41',
        (2, 18): 'MAP002.44',
        (2, 19): 'MAP002.45',
        (2, 20): 'MAP002.54',
        (2, 21): 'MAP002.55',
        (2, 22): 'MAP002.58',
        (2, 23): 'MAP002.59',
        (2, 24): 'MAP002.62',
        (2, 25): 'MAP002.63',
        (2, 26): 'MAP002.66',
        (2, 27): 'MAP002.67',
        (2, 28): 'MAP002.70',
        (2, 29): 'MAP002.71',
        (2, 30): 'MAP002.74',
        (2, 31): 'MAP002.75',
        (2, 32): 'MAP002.78',
        (2, 33): 'MAP002.79',
        (2, 34): 'MAP002.82',
        (2, 35): 'MAP002.83',
        (2, 36): 'MAP002.86',
        (2, 37): 'MAP002.87',
        (2, 38): 'MAP002.90',
        (2, 39): 'MAP002.91',
        (3, 0): 'MAP003.8',
        (3, 1): 'MAP003.9',
        (3, 2): 'MAP003.12',
        (3, 3): 'MAP003.13',
        (3, 4): 'MAP003.16',
        (3, 5): 'MAP003.17',
        (3, 6): 'MAP003.20',
        (3, 7): 'MAP003.21',
        (4, 0): 'MAP004.7',
        (4, 1): 'MAP004.8',
        (4, 2): 'MAP004.13',
        (4, 3): 'MAP004.18',
        (4, 4): 'MAP004.23',
        (4, 5): 'MAP004.24',
        (4, 6): 'MAP004.29',
        (4, 7): 'MAP004.30',
        (4, 8): 'MAP004.35',
        (4, 9): 'MAP004.36',
        (4, 10): 'MAP004.41',
        (4, 11): 'MAP004.42',
        (4, 12): 'MAP004.47',
        (4, 13): 'MAP004.48',
        (4, 14): 'MAP004.53',
        (4, 15): 'MAP004.54',
        (5, 0): 'MAP005.7',
        (5, 1): 'MAP005.8',
        (5, 2): 'MAP005.10',
        (5, 3): 'MAP005.11',
        (5, 4): 'MAP005.13',
        (5, 5): 'MAP005.14',
        (5, 6): 'MAP005.16',
        (5, 7): 'MAP005.17',
        (5, 8): 'MAP005.19',
        (5, 9): 'MAP005.20',
        (5, 10): 'MAP005.23',
        (5, 11): 'MAP005.24',
        (5, 12): 'MAP005.27',
        (5, 13): 'MAP005.28',
        (5, 14): 'MAP005.31',
        (5, 15): 'MAP005.32',
        (5, 16): 'MAP005.35',
        (5, 17): 'MAP005.36',
        (5, 18): 'MAP005.39',
        (5, 19): 'MAP005.40',
        (6, 0): 'MAP006.11',
        (6, 1): 'MAP006.12',
        (6, 2): 'MAP006.13',
        (6, 3): 'MAP006.15',
        (6, 4): 'MAP006.16',
        (6, 5): 'MAP006.20',
        (6, 6): 'MAP006.21',
        (6, 7): 'MAP006.25',
        (6, 8): 'MAP006.26',
        (6, 9): 'MAP006.31',
        (6, 10): 'MAP006.35',
        (6, 11): 'MAP006.36',
        (6, 12): 'MAP006.42',
        (6, 13): 'MAP006.43',
        (6, 14): 'MAP006.49',
        (6, 15): 'MAP006.50',
        (7, 0): 'MAP007.8',
        (7, 1): 'MAP007.9',
        (7, 2): 'MAP007.11',
        (7, 3): 'MAP007.12',
        (7, 4): 'MAP007.15',
        (7, 5): 'MAP007.16',
        (7, 6): 'MAP007.19',
        (7, 7): 'MAP007.20',
        (8, 0): 'MAP008.7',
        (8, 1): 'MAP008.8',
        (8, 2): 'MAP008.11',
        (8, 3): 'MAP008.12',
        (8, 4): 'MAP008.15',
        (8, 5): 'MAP008.16',
        (8, 6): 'MAP008.19',
        (8, 7): 'MAP008.20',
        (8, 8): 'MAP008.27',
        (8, 9): 'MAP008.28',
        (8, 10): 'MAP008.31',
        (8, 11): 'MAP008.32',
        (8, 12): 'MAP008.35',
        (8, 13): 'MAP008.36',
        (8, 14): 'MAP008.39',
        (8, 15): 'MAP008.40',
        (9, 0): 'MAP009.8',
        (9, 1): 'MAP009.9',
        (9, 2): 'MAP009.13',
        (9, 3): 'MAP009.14',
        (9, 4): 'MAP009.18',
        (9, 5): 'MAP009.19',
        (9, 6): 'MAP009.23',
        (9, 7): 'MAP009.24',
        (9, 8): 'MAP009.28',
        (9, 9): 'MAP009.29',
        (9, 10): 'MAP009.34',
        (9, 11): 'MAP009.35',
        (9, 12): 'MAP009.40',
        (9, 13): 'MAP009.41',
        (9, 14): 'MAP009.46',
        (9, 15): 'MAP009.47',
        (9, 16): 'MAP009.52',
        (9, 17): 'MAP009.53',
        (9, 18): 'MAP009.58',
        (9, 19): 'MAP009.59',
        (10, 0): 'MAP010.8',
        (10, 1): 'MAP010.9',
        (11, 0): 'MAP011.7',
        (11, 1): 'MAP011.8',
        (11, 2): 'MAP011.9',
        (11, 3): 'MAP011.11',
        (11, 4): 'MAP011.12',
        (11, 5): 'MAP011.14',
        (11, 6): 'MAP011.17',
        (11, 7): 'MAP011.18',
        (11, 8): 'MAP011.22',
        (11, 9): 'MAP011.27',
        (11, 10): 'MAP011.28',
        (11, 11): 'MAP011.33',
        (11, 12): 'MAP011.39',
        (11, 13): 'MAP011.40',
        (11, 14): 'MAP011.43',
        (11, 15): 'MAP011.47',
        (11, 16): 'MAP011.49',
        (11, 17): 'MAP011.53',
        (12, 0): 'MAP012.8',
        (12, 1): 'MAP012.9',
        (12, 2): 'MAP012.10',
        (12, 3): 'MAP012.14',
        (12, 4): 'MAP012.15',
        (12, 5): 'MAP012.19',
        (12, 6): 'MAP012.20',
        (12, 7): 'MAP012.24',
        (12, 8): 'MAP012.25',
        (12, 9): 'MAP012.26',
        (12, 10): 'MAP012.30',
        (12, 11): 'MAP012.31',
        (12, 12): 'MAP012.35',
        (12, 13): 'MAP012.36',
        (12, 14): 'MAP012.40',
        (12, 15): 'MAP012.41',
        (13, 0): 'MAP013.8',
        (13, 1): 'MAP013.9',
        (13, 2): 'MAP013.11',
        (13, 3): 'MAP013.12',
        (13, 4): 'MAP013.15',
        (13, 5): 'MAP013.16',
        (13, 6): 'MAP013.19',
        (13, 7): 'MAP013.20',
        (14, 0): 'MAP014.7',
        (14, 1): 'MAP014.8',
        (14, 2): 'MAP014.9',
        (14, 3): 'MAP014.12',
        (14, 4): 'MAP014.13',
        (14, 5): 'MAP014.16',
        (14, 6): 'MAP014.17',
        (14, 7): 'MAP014.20',
        (14, 8): 'MAP014.21',
        (14, 9): 'MAP014.25',
        (14, 10): 'MAP014.26',
        (14, 11): 'MAP014.30',
        (14, 12): 'MAP014.31',
        (14, 13): 'MAP014.35',
        (14, 14): 'MAP014.36',
        (14, 15): 'MAP014.40',
        (14, 16): 'MAP014.41',
        (15, 0): 'MAP015.8',
        (15, 1): 'MAP015.9',
        (15, 2): 'MAP015.11',
        (15, 3): 'MAP015.12',
        (15, 4): 'MAP015.14',
        (15, 5): 'MAP015.15',
        (15, 6): 'MAP015.17',
        (15, 7): 'MAP015.18',
        (15, 8): 'MAP015.20',
        (15, 9): 'MAP015.21',
        (15, 10): 'MAP015.23',
        (15, 11): 'MAP015.24',
        (15, 12): 'MAP015.26',
        (15, 13): 'MAP015.27',
        (15, 14): 'MAP015.29',
        (15, 15): 'MAP015.30',
        (15, 16): 'MAP015.32',
        (15, 17): 'MAP015.33',
        (15, 18): 'MAP015.35',
        (15, 19): 'MAP015.36',
        (15, 20): 'MAP015.45',
        (15, 21): 'MAP015.46',
        (15, 22): 'MAP015.48',
        (15, 23): 'MAP015.49',
        (15, 24): 'MAP015.51',
        (15, 25): 'MAP015.52',
        (15, 26): 'MAP015.54',
        (15, 27): 'MAP015.55',
        (15, 28): 'MAP015.57',
        (15, 29): 'MAP015.58',
        (15, 30): 'MAP015.60',
        (15, 31): 'MAP015.61',
        (15, 32): 'MAP015.63',
        (15, 33): 'MAP015.64',
        (15, 34): 'MAP015.66',
        (15, 35): 'MAP015.67',
        (15, 36): 'MAP015.69',
        (15, 37): 'MAP015.70',
        (15, 38): 'MAP015.72',
        (15, 39): 'MAP015.73',
        (16, 0): 'MAP016.8',
        (16, 1): 'MAP016.9',
        (16, 2): 'MAP016.12',
        (16, 3): 'MAP016.13',
        (16, 4): 'MAP016.16',
        (16, 5): 'MAP016.17',
        (16, 6): 'MAP016.20',
        (16, 7): 'MAP016.21',
        (16, 8): 'MAP016.30',
        (16, 9): 'MAP016.31',
        (16, 10): 'MAP016.34',
        (16, 11): 'MAP016.35',
        (16, 12): 'MAP016.38',
        (16, 13): 'MAP016.39',
        (16, 14): 'MAP016.42',
        (16, 15): 'MAP016.43',
        (17, 0): 'MAP017.9',
        (17, 1): 'MAP017.10',
        (18, 0): 'MAP018.8',
        (18, 1): 'MAP018.9',
        (18, 2): 'MAP018.13',
        (18, 3): 'MAP018.14',
        (18, 4): 'MAP018.18',
        (18, 5): 'MAP018.19',
        (18, 6): 'MAP018.23',
        (18, 7): 'MAP018.24',
        (18, 8): 'MAP018.33',
        (18, 9): 'MAP018.34',
        (18, 10): 'MAP018.38',
        (18, 11): 'MAP018.39',
        (18, 12): 'MAP018.43',
        (18, 13): 'MAP018.44',
        (18, 14): 'MAP018.48',
        (18, 15): 'MAP018.49',
        (19, 0): 'MAP019.7',
        (19, 1): 'MAP019.8',
        (19, 2): 'MAP019.11',
        (19, 3): 'MAP019.12',
        (19, 4): 'MAP019.15',
        (19, 5): 'MAP019.16',
        (19, 6): 'MAP019.19',
        (19, 7): 'MAP019.20',
        (19, 8): 'MAP019.23',
        (19, 9): 'MAP019.24',
        (19, 10): 'MAP019.27',
        (19, 11): 'MAP019.28',
        (19, 12): 'MAP019.31',
        (19, 13): 'MAP019.32',
        (19, 14): 'MAP019.35',
        (19, 15): 'MAP019.36',
        (19, 16): 'MAP019.39',
        (19, 17): 'MAP019.40',
        (19, 18): 'MAP019.43',
        (19, 19): 'MAP019.44',
        (20, 0): 'MAP020.7',
        (20, 1): 'MAP020.8',
        (20, 2): 'MAP020.11',
        (20, 3): 'MAP020.12',
        (20, 4): 'MAP020.15',
        (20, 5): 'MAP020.16',
        (20, 6): 'MAP020.19',
        (20, 7): 'MAP020.20',
        (21, 0): 'MAP021.7',
        (21, 1): 'MAP021.8',
        (21, 2): 'MAP021.15',
        (21, 3): 'MAP021.18',
        (21, 4): 'MAP021.19',
        (21, 5): 'MAP021.22',
        (21, 6): 'MAP021.23',
        (21, 7): 'MAP021.26',
        (21, 8): 'MAP021.27',
        (21, 9): 'MAP021.33',
        (21, 10): 'MAP021.38',
        (21, 11): 'MAP021.39',
        (21, 12): 'MAP021.44',
        (21, 13): 'MAP021.45',
        (21, 14): 'MAP021.50',
        (21, 15): 'MAP021.51',
        (22, 0): 'MAP022.8',
        (22, 1): 'MAP022.9',
        (22, 2): 'MAP022.12',
        (22, 3): 'MAP022.13',
        (22, 4): 'MAP022.16',
        (22, 5): 'MAP022.17',
        (22, 6): 'MAP022.20',
        (22, 7): 'MAP022.21',
        (22, 8): 'MAP022.24',
        (22, 9): 'MAP022.25',
        (22, 10): 'MAP022.30',
        (22, 11): 'MAP022.31',
        (22, 12): 'MAP022.36',
        (22, 13): 'MAP022.37',
        (22, 14): 'MAP022.42',
        (22, 15): 'MAP022.43',
        (22, 16): 'MAP022.48',
        (22, 17): 'MAP022.49',
        (22, 18): 'MAP022.54',
        (22, 19): 'MAP022.55',
        (23, 0): 'MAP023.8',
        (23, 1): 'MAP023.9',
        (23, 2): 'MAP023.10',
        (23, 3): 'MAP023.12',
        (23, 4): 'MAP023.13',
        (23, 5): 'MAP023.15',
        (23, 6): 'MAP023.16',
        (23, 7): 'MAP023.19',
        (23, 8): 'MAP023.20',
        (23, 9): 'MAP023.24',
        (23, 10): 'MAP023.25',
        (24, 0): 'MAP024.6',
        (24, 1): 'MAP024.7',
        (24, 2): 'MAP024.10',
        (24, 3): 'MAP024.11',
        (24, 4): 'MAP024.14',
        (24, 5): 'MAP024.15',
        (24, 6): 'MAP024.18',
        (24, 7): 'MAP024.19',
        (25, 0): 'MAP025.7',
        (25, 1): 'MAP025.8',
        (25, 2): 'MAP025.9',
        (25, 3): 'MAP025.12',
        (25, 4): 'MAP025.13',
        (25, 5): 'MAP025.16',
        (25, 6): 'MAP025.17',
        (25, 7): 'MAP025.20',
        (25, 8): 'MAP025.21',
        (25, 9): 'MAP025.24',
        (25, 10): 'MAP025.25',
        (26, 0): 'MAP026.8',
        (26, 1): 'MAP026.9',
        (27, 0): 'MAP027.7',
        (27, 1): 'MAP027.8',
        (27, 2): 'MAP027.10',
        (27, 3): 'MAP027.13',
        (27, 4): 'MAP027.14',
        (27, 5): 'MAP027.17',
        (27, 6): 'MAP027.18',
        (27, 7): 'MAP027.21',
        (27, 8): 'MAP027.22',
        (28, 0): 'MAP028.6',
        (28, 1): 'MAP028.7',
        (28, 2): 'MAP028.8',
        (28, 3): 'MAP028.10',
        (28, 4): 'MAP028.11',
        (28, 5): 'MAP028.13',
        (28, 6): 'MAP028.14',
        (28, 7): 'MAP028.16',
        (28, 8): 'MAP028.17',
        (29, 0): 'MAP029.7',
        (29, 1): 'MAP029.8',
        (29, 2): 'MAP029.10',
        (29, 3): 'MAP029.13',
        (29, 4): 'MAP029.14',
        (29, 5): 'MAP029.17',
        (29, 6): 'MAP029.18',
        (29, 7): 'MAP029.21',
        (29, 8): 'MAP029.22',
        (30, 0): 'MAP030.6',
        (30, 1): 'MAP030.7',
        (30, 2): 'MAP030.8',
        (30, 3): 'MAP030.11',
        (30, 4): 'MAP030.12',
        (30, 5): 'MAP030.15',
        (30, 6): 'MAP030.16',
        (30, 7): 'MAP030.19',
        (30, 8): 'MAP030.20',
        (31, 0): 'MAP031.7',
        (31, 1): 'MAP031.8',
        (31, 2): 'MAP031.11',
        (31, 3): 'MAP031.12',
        (31, 4): 'MAP031.15',
        (31, 5): 'MAP031.16',
        (31, 6): 'MAP031.19',
        (31, 7): 'MAP031.20',
        (31, 8): 'MAP031.23',
        (31, 9): 'MAP031.24',
        (31, 10): 'MAP031.27',
        (31, 11): 'MAP031.28',
        (31, 12): 'MAP031.31',
        (31, 13): 'MAP031.32',
        (31, 14): 'MAP031.35',
        (31, 15): 'MAP031.36',
        (31, 16): 'MAP031.39',
        (31, 17): 'MAP031.40',
        (31, 18): 'MAP031.43',
        (31, 19): 'MAP031.44',
        (32, 0): 'MAP032.8',
        (32, 1): 'MAP032.9',
        (32, 2): 'MAP032.11',
        (32, 3): 'MAP032.14',
        (32, 4): 'MAP032.15',
        (32, 5): 'MAP032.18',
        (32, 6): 'MAP032.19',
        (32, 7): 'MAP032.22',
        (32, 8): 'MAP032.23',
        (33, 0): 'MAP033.8',
        (33, 1): 'MAP033.9',
        (33, 2): 'MAP033.18',
        (33, 3): 'MAP033.19',
        (34, 0): 'MAP034.6',
        (34, 1): 'MAP034.7',
        (34, 2): 'MAP034.11',
        (34, 3): 'MAP034.15',
        (34, 4): 'MAP034.19',
        (35, 0): 'MAP035.7',
        (35, 1): 'MAP035.8',
        (35, 2): 'MAP035.11',
        (35, 3): 'MAP035.12',
        (35, 4): 'MAP035.15',
        (35, 5): 'MAP035.16',
        (35, 6): 'MAP035.19',
        (35, 7): 'MAP035.20',
        (35, 8): 'MAP035.23',
        (35, 9): 'MAP035.24',
        (35, 10): 'MAP035.27',
        (35, 11): 'MAP035.28',
        (35, 12): 'MAP035.31',
        (35, 13): 'MAP035.32',
        (35, 14): 'MAP035.35',
        (35, 15): 'MAP035.36',
        (35, 16): 'MAP035.39',
        (35, 17): 'MAP035.40',
        (35, 18): 'MAP035.43',
        (35, 19): 'MAP035.44',
        (36, 0): 'MAP036.1',
        (36, 1): 'MAP036.4',
        (36, 2): 'MAP036.5',
        (36, 3): 'MAP036.8',
        (36, 4): 'MAP036.9',
        (36, 5): 'MAP036.12',
        (36, 6): 'MAP036.13',
        (36, 7): 'MAP036.16',
        (36, 8): 'MAP036.17',
        (36, 9): 'MAP036.20',
        (36, 10): 'MAP036.21',
        (36, 11): 'MAP036.24',
        (36, 12): 'MAP036.25',
        (36, 13): 'MAP036.28',
        (36, 14): 'MAP036.29',
        (36, 15): 'MAP036.32',
        (36, 16): 'MAP036.33',
        (36, 17): 'MAP036.45',
        (36, 18): 'MAP036.46',
        (37, 0): 'MAP037.6',
        (37, 1): 'MAP037.7',
        (37, 2): 'MAP037.9',
        (37, 3): 'MAP037.10',
        (38, 0): 'MAP038.11',
        (38, 1): 'MAP038.12',
        (38, 2): 'MAP038.15',
        (38, 3): 'MAP038.16',
        (38, 4): 'MAP038.19',
        (38, 5): 'MAP038.20',
        (38, 6): 'MAP038.23',
        (38, 7): 'MAP038.24',
        (38, 8): 'MAP038.27',
        (38, 9): 'MAP038.28',
        (38, 10): 'MAP038.31',
        (38, 11): 'MAP038.32',
        (38, 12): 'MAP038.35',
        (38, 13): 'MAP038.36',
        (38, 14): 'MAP038.39',
        (38, 15): 'MAP038.40',
        (38, 16): 'MAP038.43',
        (38, 17): 'MAP038.44',
        (38, 18): 'MAP038.47',
        (38, 19): 'MAP038.48',
        (39, 0): 'MAP039.8',
        (39, 1): 'MAP039.9',
        (40, 0): 'MAP040.9',
        (40, 1): 'MAP040.10',
        (40, 2): 'MAP040.11',
        (40, 3): 'MAP040.13',
        (40, 4): 'MAP040.14',
        (40, 5): 'MAP040.16',
        (40, 6): 'MAP040.17',
        (40, 7): 'MAP040.19',
        (40, 8): 'MAP040.20',
        (40, 9): 'MAP040.22',
        (40, 10): 'MAP040.23',
        (40, 11): 'MAP040.25',
        (40, 12): 'MAP040.26',
        (40, 13): 'MAP040.28',
        (40, 14): 'MAP040.29',
        (40, 15): 'MAP040.31',
        (40, 16): 'MAP040.32',
        (40, 17): 'MAP040.34',
        (40, 18): 'MAP040.35',
        (41, 0): 'MAP041.5',
        (41, 1): 'MAP041.11',
        (41, 2): 'MAP041.19',
        (41, 3): 'MAP041.20',
        (42, 0): 'MAP042.8',
        (42, 1): 'MAP042.9',
        (42, 2): 'MAP042.12',
        (42, 3): 'MAP042.13',
        (42, 4): 'MAP042.16',
        (42, 5): 'MAP042.17',
        (42, 6): 'MAP042.20',
        (42, 7): 'MAP042.21',
        (42, 8): 'MAP042.24',
        (42, 9): 'MAP042.25',
        (43, 0): 'MAP043.8',
        (43, 1): 'MAP043.9',
        (43, 2): 'MAP043.12',
        (43, 3): 'MAP043.13',
        (44, 0): 'MAP044.7',
        (44, 1): 'MAP044.8',
        (44, 2): 'MAP044.11',
        (44, 3): 'MAP044.12',
        (44, 4): 'MAP044.15',
        (44, 5): 'MAP044.16',
        (44, 6): 'MAP044.19',
        (44, 7): 'MAP044.20',
        (44, 8): 'MAP044.23',
        (44, 9): 'MAP044.24',
        (44, 10): 'MAP044.27',
        (44, 11): 'MAP044.28',
        (44, 12): 'MAP044.31',
        (44, 13): 'MAP044.32',
        (44, 14): 'MAP044.35',
        (44, 15): 'MAP044.36',
        (44, 16): 'MAP044.39',
        (44, 17): 'MAP044.40',
        (44, 18): 'MAP044.43',
        (44, 19): 'MAP044.44',
        (45, 0): 'MAP045.6',
        (45, 1): 'MAP045.7',
        (45, 2): 'MAP045.10',
        (45, 3): 'MAP045.11',
        (46, 0): 'MAP046.8',
        (46, 1): 'MAP046.9',
        (46, 2): 'MAP046.12',
        (46, 3): 'MAP046.13',
        (46, 4): 'MAP046.16',
        (46, 5): 'MAP046.17',
        (46, 6): 'MAP046.20',
        (46, 7): 'MAP046.21',
        (46, 8): 'MAP046.24',
        (46, 9): 'MAP046.25',
        (47, 0): 'MAP047.16',
        (47, 1): 'MAP047.17',
        (47, 2): 'MAP047.20',
        (47, 3): 'MAP047.21',
        (47, 4): 'MAP047.25',
        (47, 5): 'MAP047.26',
        (47, 6): 'MAP047.30',
        (47, 7): 'MAP047.31',
        (47, 8): 'MAP047.35',
        (47, 9): 'MAP047.36',
        (47, 10): 'MAP047.40',
        (47, 11): 'MAP047.41',
        (47, 12): 'MAP047.45',
        (47, 13): 'MAP047.46',
        (47, 14): 'MAP047.50',
        (47, 15): 'MAP047.51',
        (47, 16): 'MAP047.55',
        (47, 17): 'MAP047.56',
        (47, 18): 'MAP047.60',
        (47, 19): 'MAP047.61',
        (48, 0): 'MAP048.8',
        (48, 1): 'MAP048.9',
        (48, 2): 'MAP048.12',
        (48, 3): 'MAP048.13',
        (48, 4): 'MAP048.16',
        (48, 5): 'MAP048.17',
        (48, 6): 'MAP048.20',
        (48, 7): 'MAP048.21',
        (48, 8): 'MAP048.24',
        (48, 9): 'MAP048.25',
        (48, 10): 'MAP048.28',
        (48, 11): 'MAP048.29',
        (48, 12): 'MAP048.32',
        (48, 13): 'MAP048.33',
        (48, 14): 'MAP048.36',
        (48, 15): 'MAP048.37',
        (48, 16): 'MAP048.40',
        (48, 17): 'MAP048.41',
        (48, 18): 'MAP048.44',
        (48, 19): 'MAP048.45',
        (49, 0): 'MAP049.7',
        (49, 1): 'MAP049.8',
        (49, 2): 'MAP049.10',
        (49, 3): 'MAP049.11',
        (49, 4): 'MAP049.14',
        (49, 5): 'MAP049.15',
        (49, 6): 'MAP049.18',
        (49, 7): 'MAP049.19',
        (49, 8): 'MAP049.22',
        (49, 9): 'MAP049.23',
        (49, 10): 'MAP049.26',
        (49, 11): 'MAP049.27',
        (49, 12): 'MAP049.30',
        (49, 13): 'MAP049.31',
        (49, 14): 'MAP049.34',
        (49, 15): 'MAP049.35',
        (49, 16): 'MAP049.38',
        (49, 17): 'MAP049.39',
        (49, 18): 'MAP049.42',
        (49, 19): 'MAP049.43',
        (50, 0): 'MAP050.7',
        (50, 1): 'MAP050.8',
        (50, 2): 'MAP050.11',
        (50, 3): 'MAP050.12',
        (50, 4): 'MAP050.15',
        (50, 5): 'MAP050.16',
        (50, 6): 'MAP050.19',
        (50, 7): 'MAP050.20',
        (50, 8): 'MAP050.23',
        (50, 9): 'MAP050.24',
        (50, 10): 'MAP050.27',
        (50, 11): 'MAP050.28',
        (50, 12): 'MAP050.31',
        (50, 13): 'MAP050.32',
        (50, 14): 'MAP050.35',
        (50, 15): 'MAP050.36',
        (50, 16): 'MAP050.39',
        (50, 17): 'MAP050.40',
        (50, 18): 'MAP050.43',
        (50, 19): 'MAP050.44',
        (51, 0): 'MAP051.7',
        (51, 1): 'MAP051.8',
        (51, 2): 'MAP051.16',
        (51, 3): 'MAP051.17',
        (51, 4): 'MAP051.20',
        (51, 5): 'MAP051.21',
        (51, 6): 'MAP051.24',
        (51, 7): 'MAP051.25',
        (51, 8): 'MAP051.28',
        (51, 9): 'MAP051.29',
        (51, 10): 'MAP051.32',
        (51, 11): 'MAP051.37',
        (51, 12): 'MAP051.38',
        (51, 13): 'MAP051.43',
        (51, 14): 'MAP051.44',
        (51, 15): 'MAP051.49',
        (51, 16): 'MAP051.50',
        (52, 0): 'MAP052.9',
        (52, 1): 'MAP052.10',
        (53, 0): 'MAP053.7',
        (53, 1): 'MAP053.8',
        (53, 2): 'MAP053.10',
        (53, 3): 'MAP053.19',
        (53, 4): 'MAP053.22',
        (54, 0): 'MAP054.7',
        (54, 1): 'MAP054.8',
        (55, 0): 'MAP055.12',
        (55, 1): 'MAP055.13',
        (55, 2): 'MAP055.14',
        (55, 3): 'MAP055.15',
        (56, 0): 'MAP056.0',
        (56, 1): 'MAP056.3',
        (56, 2): 'MAP056.4',
        (56, 3): 'MAP056.7',
        (56, 4): 'MAP056.8',
        (56, 5): 'MAP056.11',
        (56, 6): 'MAP056.12',
        (56, 7): 'MAP056.16',
        (56, 8): 'MAP056.17',
        (56, 9): 'MAP056.21',
        (56, 10): 'MAP056.22',
        (56, 11): 'MAP056.26',
        (56, 12): 'MAP056.27',
        (56, 13): 'MAP056.31',
        (56, 14): 'MAP056.32',
        (56, 15): 'MAP056.36',
        (56, 16): 'MAP056.37',
        (56, 17): 'MAP056.47',
        (56, 18): 'MAP056.48',
        (57, 0): 'MAP057.8',
        (57, 1): 'MAP057.9',
        (58, 0): 'MAP058.8',
        (58, 1): 'MAP058.9',
        (59, 0): 'MAP059.8',
        (59, 1): 'MAP059.9',
        (60, 0): 'MAP060.8',
        (60, 1): 'MAP060.9',
        (61, 0): 'MAP061.7',
        (61, 1): 'MAP061.8',
        (61, 2): 'MAP061.9',
        (61, 3): 'MAP061.10',
        (62, 0): 'MAP062.7',
        (62, 1): 'MAP062.8',
        (62, 2): 'MAP062.11',
        (62, 3): 'MAP062.12',
        (62, 4): 'MAP062.15',
        (62, 5): 'MAP062.16',
        (62, 6): 'MAP062.19',
        (62, 7): 'MAP062.20',
        (63, 0): 'MAP063.6',
        (63, 1): 'MAP063.7',
        (63, 2): 'MAP063.10',
        (63, 3): 'MAP063.11',
        (63, 4): 'MAP063.14',
        (63, 5): 'MAP063.15',
        (63, 6): 'MAP063.18',
        (63, 7): 'MAP063.19',
        (63, 8): 'MAP063.22',
        (63, 9): 'MAP063.23',
        (64, 0): 'MAP064.9',
        (64, 1): 'MAP064.10',
        (64, 2): 'MAP064.14',
        (64, 3): 'MAP064.19',
        (65, 0): 'MAP065.8',
        (65, 1): 'MAP065.9',
        (66, 0): 'MAP066.7',
        (66, 1): 'MAP066.8',
        (66, 2): 'MAP066.9',
        (66, 3): 'MAP066.12',
        (66, 4): 'MAP066.13',
        (66, 5): 'MAP066.16',
        (66, 6): 'MAP066.17',
        (66, 7): 'MAP066.20',
        (66, 8): 'MAP066.21',
        (66, 9): 'MAP066.24',
        (66, 10): 'MAP066.25',
        (66, 11): 'MAP066.28',
        (66, 12): 'MAP066.29',
        (66, 13): 'MAP066.32',
        (66, 14): 'MAP066.33',
        (66, 15): 'MAP066.36',
        (66, 16): 'MAP066.37',
        (66, 17): 'MAP066.40',
        (66, 18): 'MAP066.41',
        (67, 0): 'MAP067.7',
        (67, 1): 'MAP067.8',
        (67, 2): 'MAP067.9',
        (67, 3): 'MAP067.12',
        (67, 4): 'MAP067.13',
        (67, 5): 'MAP067.16',
        (67, 6): 'MAP067.17',
        (67, 7): 'MAP067.20',
        (67, 8): 'MAP067.21',
        (67, 9): 'MAP067.24',
        (67, 10): 'MAP067.25',
        (67, 11): 'MAP067.28',
        (67, 12): 'MAP067.29',
        (67, 13): 'MAP067.32',
        (67, 14): 'MAP067.33',
        (67, 15): 'MAP067.36',
        (67, 16): 'MAP067.37',
        (67, 17): 'MAP067.40',
        (67, 18): 'MAP067.41',
        (68, 0): 'MAP068.7',
        (68, 1): 'MAP068.8',
        (68, 2): 'MAP068.11',
        (68, 3): 'MAP068.12',
        (68, 4): 'MAP068.15',
        (68, 5): 'MAP068.16',
        (68, 6): 'MAP068.19',
        (68, 7): 'MAP068.20',
        (68, 8): 'MAP068.28',
        (68, 9): 'MAP068.29',
        (68, 10): 'MAP068.32',
        (68, 11): 'MAP068.33',
        (68, 12): 'MAP068.36',
        (68, 13): 'MAP068.37',
        (68, 14): 'MAP068.40',
        (68, 15): 'MAP068.41',
        (69, 0): 'MAP069.7',
        (69, 1): 'MAP069.8',
        (70, 0): 'MAP070.6',
        (70, 1): 'MAP070.7',
        (70, 2): 'MAP070.10',
        (70, 3): 'MAP070.11',
        (71, 0): 'MAP071.8',
        (71, 1): 'MAP071.9',
        (71, 2): 'MAP071.12',
        (71, 3): 'MAP071.13',
        (71, 4): 'MAP071.16',
        (71, 5): 'MAP071.17',
        (71, 6): 'MAP071.20',
        (71, 7): 'MAP071.21',
        (71, 8): 'MAP071.24',
        (71, 9): 'MAP071.25',
        (71, 10): 'MAP071.28',
        (71, 11): 'MAP071.29',
        (71, 12): 'MAP071.32',
        (71, 13): 'MAP071.33',
        (71, 14): 'MAP071.36',
        (71, 15): 'MAP071.37',
        (71, 16): 'MAP071.40',
        (71, 17): 'MAP071.41',
        (71, 18): 'MAP071.44',
        (71, 19): 'MAP071.45',
        (72, 0): 'MAP072.8',
        (72, 1): 'MAP072.9',
        (72, 2): 'MAP072.10',
        (72, 3): 'MAP072.13',
        (72, 4): 'MAP072.14',
        (72, 5): 'MAP072.17',
        (72, 6): 'MAP072.18',
        (72, 7): 'MAP072.20',
        (72, 8): 'MAP072.21',
        (72, 9): 'MAP072.23',
        (72, 10): 'MAP072.26',
        (72, 11): 'MAP072.27',
        (72, 12): 'MAP072.30',
        (72, 13): 'MAP072.31',
        (72, 14): 'MAP072.34',
        (72, 15): 'MAP072.35',
        (72, 16): 'MAP072.38',
        (72, 17): 'MAP072.39',
        (73, 0): 'MAP073.2',
        (73, 1): 'MAP073.3',
        (73, 2): 'MAP073.6',
        (73, 3): 'MAP073.7',
        (73, 4): 'MAP073.10',
        (73, 5): 'MAP073.11',
        (73, 6): 'MAP073.23',
        (73, 7): 'MAP073.24',
        (74, 0): 'MAP074.8',
        (74, 1): 'MAP074.9',
        (74, 2): 'MAP074.10',
        (74, 3): 'MAP074.12',
        (74, 4): 'MAP074.13',
        (74, 5): 'MAP074.15',
        (74, 6): 'MAP074.16',
        (74, 7): 'MAP074.18',
        (74, 8): 'MAP074.19',
        (74, 9): 'MAP074.21',
        (74, 10): 'MAP074.22',
        (74, 11): 'MAP074.24',
        (74, 12): 'MAP074.25',
        (74, 13): 'MAP074.27',
        (74, 14): 'MAP074.28',
        (74, 15): 'MAP074.30',
        (74, 16): 'MAP074.31',
        (74, 17): 'MAP074.33',
        (74, 18): 'MAP074.34',
        (75, 0): 'MAP075.8',
        (75, 1): 'MAP075.9',
        (75, 2): 'MAP075.11',
        (75, 3): 'MAP075.12',
        (75, 4): 'MAP075.14',
        (75, 5): 'MAP075.15',
        (75, 6): 'MAP075.17',
        (75, 7): 'MAP075.18',
        (75, 8): 'MAP075.20',
        (75, 9): 'MAP075.21',
        (75, 10): 'MAP075.25',
        (75, 11): 'MAP075.26',
        (75, 12): 'MAP075.30',
        (75, 13): 'MAP075.31',
        (75, 14): 'MAP075.35',
        (75, 15): 'MAP075.36',
        (75, 16): 'MAP075.40',
        (75, 17): 'MAP075.41',
        (75, 18): 'MAP075.45',
        (75, 19): 'MAP075.46',
        (76, 0): 'MAP076.6',
        (76, 1): 'MAP076.7',
        (76, 2): 'MAP076.9',
        (76, 3): 'MAP076.11',
        (76, 4): 'MAP076.14',
        (76, 5): 'MAP076.15',
        (76, 6): 'MAP076.18',
        (76, 7): 'MAP076.19',
        (76, 8): 'MAP076.21',
        (76, 9): 'MAP076.24',
        (76, 10): 'MAP076.25',
        (76, 11): 'MAP076.28',
        (76, 12): 'MAP076.29',
        (76, 13): 'MAP076.32',
        (76, 14): 'MAP076.33',
        (76, 15): 'MAP076.36',
        (76, 16): 'MAP076.37',
        (77, 0): 'MAP077.8',
        (77, 1): 'MAP077.9',
        (77, 2): 'MAP077.11',
        (77, 3): 'MAP077.12',
        (77, 4): 'MAP077.14',
        (77, 5): 'MAP077.15',
        (77, 6): 'MAP077.17',
        (77, 7): 'MAP077.18',
        (77, 8): 'MAP077.20',
        (77, 9): 'MAP077.21',
        (77, 10): 'MAP077.25',
        (77, 11): 'MAP077.26',
        (77, 12): 'MAP077.30',
        (77, 13): 'MAP077.31',
        (77, 14): 'MAP077.35',
        (77, 15): 'MAP077.36',
        (77, 16): 'MAP077.40',
        (77, 17): 'MAP077.41',
        (77, 18): 'MAP077.45',
        (77, 19): 'MAP077.46',
        (78, 0): 'MAP078.8',
        (78, 1): 'MAP078.9',
        (78, 2): 'MAP078.13',
        (78, 3): 'MAP078.14',
        (78, 4): 'MAP078.18',
        (78, 5): 'MAP078.19',
        (78, 6): 'MAP078.22',
        (78, 7): 'MAP078.23',
        (78, 8): 'MAP078.26',
        (78, 9): 'MAP078.27',
        (78, 10): 'MAP078.31',
        (78, 11): 'MAP078.32',
        (78, 12): 'MAP078.35',
        (78, 13): 'MAP078.36',
        (78, 14): 'MAP078.39',
        (78, 15): 'MAP078.40',
        (78, 16): 'MAP078.43',
        (78, 17): 'MAP078.44',
        (78, 18): 'MAP078.47',
        (78, 19): 'MAP078.48',
        (79, 0): 'MAP079.6',
        (79, 1): 'MAP079.7',
        (79, 2): 'MAP079.8',
        (79, 3): 'MAP079.9',
        (79, 4): 'MAP079.10',
        (79, 5): 'MAP079.11',
        (79, 6): 'MAP079.12',
        (79, 7): 'MAP079.13',
        (79, 8): 'MAP079.14',
        (79, 9): 'MAP079.15',
        (79, 10): 'MAP079.16',
        (80, 0): 'MAP080.6',
        (80, 1): 'MAP080.7',
        (80, 2): 'MAP080.8',
        (80, 3): 'MAP080.11',
        (80, 4): 'MAP080.12',
        (80, 5): 'MAP080.15',
        (80, 6): 'MAP080.16',
        (80, 7): 'MAP080.19',
        (80, 8): 'MAP080.20',
        (80, 9): 'MAP080.23',
        (80, 10): 'MAP080.24',
        (80, 11): 'MAP080.27',
        (80, 12): 'MAP080.28',
        (80, 13): 'MAP080.31',
        (80, 14): 'MAP080.32',
        (80, 15): 'MAP080.35',
        (80, 16): 'MAP080.36',
        (80, 17): 'MAP080.39',
        (80, 18): 'MAP080.40',
        (81, 0): 'MAP081.6',
        (81, 1): 'MAP081.7',
        (81, 2): 'MAP081.10',
        (81, 3): 'MAP081.11',
        (81, 4): 'MAP081.14',
        (81, 5): 'MAP081.15',
        (81, 6): 'MAP081.18',
        (81, 7): 'MAP081.19',
        (81, 8): 'MAP081.22',
        (81, 9): 'MAP081.23',
        (81, 10): 'MAP081.26',
        (81, 11): 'MAP081.27',
        (81, 12): 'MAP081.30',
        (81, 13): 'MAP081.31',
        (81, 14): 'MAP081.34',
        (81, 15): 'MAP081.35',
        (81, 16): 'MAP081.38',
        (81, 17): 'MAP081.39',
        (81, 18): 'MAP081.42',
        (81, 19): 'MAP081.43',
        (82, 0): 'MAP082.6',
        (82, 1): 'MAP082.7',
        (82, 2): 'MAP082.9',
        (82, 3): 'MAP082.11',
        (82, 4): 'MAP082.14',
        (82, 5): 'MAP082.15',
        (82, 6): 'MAP082.18',
        (82, 7): 'MAP082.19',
        (82, 8): 'MAP082.21',
        (82, 9): 'MAP082.24',
        (82, 10): 'MAP082.25',
        (82, 11): 'MAP082.28',
        (82, 12): 'MAP082.29',
        (82, 13): 'MAP082.32',
        (82, 14): 'MAP082.33',
        (82, 15): 'MAP082.36',
        (82, 16): 'MAP082.37',
        (83, 0): 'MAP083.8',
        (83, 1): 'MAP083.9',
        (83, 2): 'MAP083.10',
        (83, 3): 'MAP083.12',
        (83, 4): 'MAP083.14',
        (83, 5): 'MAP083.16',
        (83, 6): 'MAP083.18',
        (83, 7): 'MAP083.20',
        (83, 8): 'MAP083.22',
        (83, 9): 'MAP083.24',
        (83, 10): 'MAP083.26',
        (83, 11): 'MAP083.28',
        (83, 12): 'MAP083.38',
        (84, 0): 'MAP084.6',
        (84, 1): 'MAP084.7',
        (84, 2): 'MAP084.10',
        (84, 3): 'MAP084.11',
        (84, 4): 'MAP084.14',
        (84, 5): 'MAP084.15',
        (84, 6): 'MAP084.18',
        (84, 7): 'MAP084.19',
        (84, 8): 'MAP084.22',
        (84, 9): 'MAP084.23',
        (84, 10): 'MAP084.26',
        (84, 11): 'MAP084.27',
        (84, 12): 'MAP084.30',
        (84, 13): 'MAP084.31',
        (84, 14): 'MAP084.34',
        (84, 15): 'MAP084.35',
        (84, 16): 'MAP084.38',
        (84, 17): 'MAP084.39',
        (84, 18): 'MAP084.42',
        (84, 19): 'MAP084.43',
        (85, 0): 'MAP085.6',
        (85, 1): 'MAP085.7',
        (85, 2): 'MAP085.9',
        (85, 3): 'MAP085.10',
        (85, 4): 'MAP085.12',
        (85, 5): 'MAP085.13',
        (85, 6): 'MAP085.15',
        (85, 7): 'MAP085.16',
        (85, 8): 'MAP085.18',
        (85, 9): 'MAP085.19',
        (85, 10): 'MAP085.21',
        (85, 11): 'MAP085.22',
        (85, 12): 'MAP085.24',
        (85, 13): 'MAP085.25',
        (85, 14): 'MAP085.27',
        (85, 15): 'MAP085.28',
        (85, 16): 'MAP085.30',
        (85, 17): 'MAP085.31',
        (85, 18): 'MAP085.33',
        (85, 19): 'MAP085.34',
        (86, 0): 'MAP086.6',
        (86, 1): 'MAP086.7',
        (86, 2): 'MAP086.9',
        (86, 3): 'MAP086.10',
        (86, 4): 'MAP086.12',
        (86, 5): 'MAP086.13',
        (86, 6): 'MAP086.15',
        (86, 7): 'MAP086.16',
        (86, 8): 'MAP086.18',
        (86, 9): 'MAP086.19',
        (86, 10): 'MAP086.21',
        (86, 11): 'MAP086.22',
        (86, 12): 'MAP086.24',
        (86, 13): 'MAP086.25',
        (86, 14): 'MAP086.27',
        (86, 15): 'MAP086.28',
        (86, 16): 'MAP086.30',
        (86, 17): 'MAP086.31',
        (86, 18): 'MAP086.33',
        (86, 19): 'MAP086.34',
        (87, 0): 'MAP087.8',
        (87, 1): 'MAP087.9',
        (87, 2): 'MAP087.10',
        (87, 3): 'MAP087.11',
        (87, 4): 'MAP087.12',
        (87, 5): 'MAP087.13',
        (87, 6): 'MAP087.14',
        (87, 7): 'MAP087.15',
        (87, 8): 'MAP087.16',
        (87, 9): 'MAP087.17',
        (87, 10): 'MAP087.18',
        (88, 0): 'MAP088.8',
        (88, 1): 'MAP088.9',
        (88, 2): 'MAP088.11',
        (88, 3): 'MAP088.12',
        (88, 4): 'MAP088.14',
        (88, 5): 'MAP088.15',
        (88, 6): 'MAP088.17',
        (88, 7): 'MAP088.18',
        (88, 8): 'MAP088.20',
        (88, 9): 'MAP088.21',
        (88, 10): 'MAP088.23',
        (88, 11): 'MAP088.24',
        (88, 12): 'MAP088.26',
        (88, 13): 'MAP088.27',
        (88, 14): 'MAP088.29',
        (88, 15): 'MAP088.30',
        (88, 16): 'MAP088.32',
        (88, 17): 'MAP088.33',
        (88, 18): 'MAP088.35',
        (88, 19): 'MAP088.36',
        (89, 0): 'MAP089.6',
        (89, 1): 'MAP089.7',
        (89, 2): 'MAP089.10',
        (89, 3): 'MAP089.11',
        (89, 4): 'MAP089.14',
        (89, 5): 'MAP089.15',
        (89, 6): 'MAP089.18',
        (89, 7): 'MAP089.19',
        (89, 8): 'MAP089.22',
        (89, 9): 'MAP089.23',
        (89, 10): 'MAP089.26',
        (89, 11): 'MAP089.27',
        (89, 12): 'MAP089.30',
        (89, 13): 'MAP089.31',
        (89, 14): 'MAP089.34',
        (89, 15): 'MAP089.35',
        (89, 16): 'MAP089.38',
        (89, 17): 'MAP089.39',
        (89, 18): 'MAP089.42',
        (89, 19): 'MAP089.43',
        (90, 0): 'MAP090.6',
        (90, 1): 'MAP090.7',
        (90, 2): 'MAP090.10',
        (90, 3): 'MAP090.11',
        (90, 4): 'MAP090.14',
        (90, 5): 'MAP090.15',
        (90, 6): 'MAP090.18',
        (90, 7): 'MAP090.19',
        (90, 8): 'MAP090.22',
        (90, 9): 'MAP090.23',
        (90, 10): 'MAP090.26',
        (90, 11): 'MAP090.27',
        (90, 12): 'MAP090.30',
        (90, 13): 'MAP090.31',
        (90, 14): 'MAP090.34',
        (90, 15): 'MAP090.35',
        (90, 16): 'MAP090.38',
        (90, 17): 'MAP090.39',
        (90, 18): 'MAP090.42',
        (90, 19): 'MAP090.43',
        (91, 0): 'MAP091.8',
        (91, 1): 'MAP091.9',
        (91, 2): 'MAP091.10',
        (91, 3): 'MAP091.13',
        (91, 4): 'MAP091.14',
        (91, 5): 'MAP091.17',
        (91, 6): 'MAP091.18',
        (91, 7): 'MAP091.21',
        (91, 8): 'MAP091.22',
        (92, 0): 'MAP092.8',
        (92, 1): 'MAP092.9',
        (92, 2): 'MAP092.12',
        (92, 3): 'MAP092.13',
        (92, 4): 'MAP092.16',
        (92, 5): 'MAP092.17',
        (92, 6): 'MAP092.20',
        (92, 7): 'MAP092.21',
        (92, 8): 'MAP092.30',
        (92, 9): 'MAP092.31',
        (92, 10): 'MAP092.34',
        (92, 11): 'MAP092.35',
        (92, 12): 'MAP092.38',
        (92, 13): 'MAP092.39',
        (92, 14): 'MAP092.42',
        (92, 15): 'MAP092.43',
        (93, 0): 'MAP093.6',
        (93, 1): 'MAP093.7',
        (93, 2): 'MAP093.10',
        (93, 3): 'MAP093.11',
        (93, 4): 'MAP093.14',
        (93, 5): 'MAP093.15',
        (93, 6): 'MAP093.18',
        (93, 7): 'MAP093.19',
        (94, 0): 'MAP094.7',
        (94, 1): 'MAP094.8',
        (94, 2): 'MAP094.16',
        (94, 3): 'MAP094.17',
        (95, 0): 'MAP095.7',
        (95, 1): 'MAP095.8',
        (95, 2): 'MAP095.11',
        (95, 3): 'MAP095.12',
        (95, 4): 'MAP095.15',
        (95, 5): 'MAP095.16',
        (95, 6): 'MAP095.19',
        (95, 7): 'MAP095.20',
        (95, 8): 'MAP095.28',
        (95, 9): 'MAP095.29',
        (95, 10): 'MAP095.32',
        (95, 11): 'MAP095.33',
        (95, 12): 'MAP095.36',
        (95, 13): 'MAP095.37',
        (95, 14): 'MAP095.40',
        (95, 15): 'MAP095.41',
        (96, 0): 'MAP096.7',
        (96, 1): 'MAP096.8',
        (96, 2): 'MAP096.12',
        (96, 3): 'MAP096.13',
        (96, 4): 'MAP096.16',
        (96, 5): 'MAP096.17',
        (96, 6): 'MAP096.20',
        (96, 7): 'MAP096.21',
        (97, 0): 'MAP097.7',
        (97, 1): 'MAP097.8',
        (97, 2): 'MAP097.11',
        (97, 3): 'MAP097.12',
        (97, 4): 'MAP097.15',
        (97, 5): 'MAP097.16',
        (97, 6): 'MAP097.18',
        (97, 7): 'MAP097.19',
        (97, 8): 'MAP097.21',
        (97, 9): 'MAP097.22',
        (97, 10): 'MAP097.25',
        (97, 11): 'MAP097.26',
        (97, 12): 'MAP097.29',
        (97, 13): 'MAP097.30',
        (97, 14): 'MAP097.33',
        (97, 15): 'MAP097.34',
        (97, 16): 'MAP097.37',
        (97, 17): 'MAP097.38',
        (97, 18): 'MAP097.41',
        (97, 19): 'MAP097.42',
        (98, 0): 'MAP098.6',
        (98, 1): 'MAP098.7',
        (98, 2): 'MAP098.10',
        (98, 3): 'MAP098.11',
        (98, 4): 'MAP098.14',
        (98, 5): 'MAP098.15',
        (98, 6): 'MAP098.18',
        (98, 7): 'MAP098.19',
        (98, 8): 'MAP098.22',
        (98, 9): 'MAP098.23',
        (98, 10): 'MAP098.26',
        (98, 11): 'MAP098.27',
        (98, 12): 'MAP098.30',
        (98, 13): 'MAP098.31',
        (98, 14): 'MAP098.34',
        (98, 15): 'MAP098.35',
        (98, 16): 'MAP098.38',
        (98, 17): 'MAP098.39',
        (98, 18): 'MAP098.42',
        (98, 19): 'MAP098.43',
        (99, 0): 'MAP099.6',
        (99, 1): 'MAP099.7',
        (99, 2): 'MAP099.10',
        (99, 3): 'MAP099.11',
        (99, 4): 'MAP099.14',
        (99, 5): 'MAP099.15',
        (99, 6): 'MAP099.18',
        (99, 7): 'MAP099.19',
        (99, 8): 'MAP099.22',
        (99, 9): 'MAP099.23',
        (99, 10): 'MAP099.26',
        (99, 11): 'MAP099.27',
        (99, 12): 'MAP099.30',
        (99, 13): 'MAP099.31',
        (99, 14): 'MAP099.34',
        (99, 15): 'MAP099.35',
        (99, 16): 'MAP099.38',
        (99, 17): 'MAP099.39',
        (99, 18): 'MAP099.42',
        (99, 19): 'MAP099.43',
        (100, 0): 'MAP100.7',
        (100, 1): 'MAP100.8',
        (101, 0): 'MAP101.9',
        (101, 1): 'MAP101.10',
        (102, 0): 'MAP102.7',
        (102, 1): 'MAP102.8',
        (103, 0): 'MAP103.9',
        (103, 1): 'MAP103.10',
        (103, 2): 'MAP103.11',
        (103, 3): 'MAP103.13',
        (103, 4): 'MAP103.14',
        (103, 5): 'MAP103.16',
        (103, 6): 'MAP103.17',
        (103, 7): 'MAP103.19',
        (103, 8): 'MAP103.20',
        (103, 9): 'MAP103.23',
        (103, 10): 'MAP103.24',
        (103, 11): 'MAP103.27',
        (103, 12): 'MAP103.28',
        (103, 13): 'MAP103.31',
        (103, 14): 'MAP103.32',
        (103, 15): 'MAP103.35',
        (103, 16): 'MAP103.36',
        (103, 17): 'MAP103.39',
        (103, 18): 'MAP103.40',
        (104, 0): 'MAP104.8',
        (104, 1): 'MAP104.9',
        (104, 2): 'MAP104.10',
        (105, 0): 'MAP105.6',
        (105, 1): 'MAP105.7',
        (105, 2): 'MAP105.14',
        (105, 3): 'MAP105.15',
        (105, 4): 'MAP105.17',
        (105, 5): 'MAP105.19',
        (105, 6): 'MAP105.21',
        (105, 7): 'MAP105.23',
        (106, 0): 'MAP106.6',
        (106, 1): 'MAP106.7',
        (106, 2): 'MAP106.9',
        (106, 3): 'MAP106.11',
        (106, 4): 'MAP106.13',
        (106, 5): 'MAP106.15',
        (106, 6): 'MAP106.17',
        (107, 0): 'MAP107.6',
        (107, 1): 'MAP107.7',
        (107, 2): 'MAP107.9',
        (107, 3): 'MAP107.11',
        (107, 4): 'MAP107.13',
        (107, 5): 'MAP107.15',
        (107, 6): 'MAP107.17',
        (108, 0): 'MAP108.6',
        (108, 1): 'MAP108.7',
        (108, 2): 'MAP108.9',
        (108, 3): 'MAP108.11',
        (108, 4): 'MAP108.13',
        (108, 5): 'MAP108.15',
        (108, 6): 'MAP108.17',
        (109, 0): 'MAP109.6',
        (109, 1): 'MAP109.7',
        (109, 2): 'MAP109.9',
        (109, 3): 'MAP109.11',
        (109, 4): 'MAP109.13',
        (109, 5): 'MAP109.15',
        (109, 6): 'MAP109.17',
        (110, 0): 'MAP110.6',
        (110, 1): 'MAP110.7',
        (110, 2): 'MAP110.9',
        (110, 3): 'MAP110.11',
        (110, 4): 'MAP110.13',
        (110, 5): 'MAP110.15',
        (110, 6): 'MAP110.17',
        (111, 0): 'MAP111.8',
        (111, 1): 'MAP111.9',
        (111, 2): 'MAP111.11',
        (111, 3): 'MAP111.13',
        (111, 4): 'MAP111.15',
        (111, 5): 'MAP111.17',
        (111, 6): 'MAP111.19',
        (112, 0): 'MAP112.6',
        (112, 1): 'MAP112.7',
        (112, 2): 'MAP112.8',
        (112, 3): 'MAP112.10',
        (112, 4): 'MAP112.12',
        (112, 5): 'MAP112.14',
        (112, 6): 'MAP112.16',
        (113, 0): 'MAP113.6',
        (113, 1): 'MAP113.7',
        (113, 2): 'MAP113.9',
        (113, 3): 'MAP113.11',
        (113, 4): 'MAP113.13',
        (113, 5): 'MAP113.15',
        (113, 6): 'MAP113.17',
        (114, 0): 'MAP114.6',
        (114, 1): 'MAP114.7',
        (114, 2): 'MAP114.9',
        (114, 3): 'MAP114.11',
        (114, 4): 'MAP114.13',
        (114, 5): 'MAP114.15',
        (114, 6): 'MAP114.17',
        (115, 0): 'MAP115.6',
        (115, 1): 'MAP115.7',
        (115, 2): 'MAP115.10',
        (115, 3): 'MAP115.11',
        (115, 4): 'MAP115.14',
        (115, 5): 'MAP115.15',
        (115, 6): 'MAP115.18',
        (115, 7): 'MAP115.19',
        (115, 8): 'MAP115.22',
        (115, 9): 'MAP115.23',
        (115, 10): 'MAP115.26',
        (115, 11): 'MAP115.27',
        (115, 12): 'MAP115.30',
        (115, 13): 'MAP115.31',
        (115, 14): 'MAP115.34',
        (115, 15): 'MAP115.35',
        (115, 16): 'MAP115.38',
        (115, 17): 'MAP115.39',
        (115, 18): 'MAP115.42',
        (115, 19): 'MAP115.43',
        (116, 0): 'MAP116.6',
        (116, 1): 'MAP116.7',
        (117, 0): 'MAP117.6',
        (117, 1): 'MAP117.7',
        (118, 0): 'MAP118.6',
        (118, 1): 'MAP118.7',
        (119, 0): 'MAP119.6',
        (119, 1): 'MAP119.7',
        (125, 0): 'MAP125.6',
        (125, 1): 'MAP125.7',
}


################################ fft/map/__init__.py ################################

class VertexTex(object):
    def __init__(self, point, normalData=None, texcoordData=None):
        self.point = point
        self.normal = Normal.from_buffer_copy(normalData).toTuple()
        self.texcoord = ubyte2_t.from_buffer_copy(texcoordData).toTuple()

class VertexUntex(object):
    def __init__(self, point, normalData=None, texcoordData=None):
        self.point = point

class TriangleTex(object):
    def from_data(self, pointData, visangle, normalData=None, texcoordData=None, terrainCoordsData=None, unknown5=None):
        self.A = VertexTex(
            short3_t.from_buffer_copy(pointData[0:6]).toTuple(),
            normalData[0:6],
            texcoordData[0:2])
        self.B = VertexTex(
            short3_t.from_buffer_copy(pointData[6:12]).toTuple(),
            normalData[6:12],
            texcoordData[4:6])
        self.C = VertexTex(
            short3_t.from_buffer_copy(pointData[12:18]).toTuple(),
            normalData[12:18],
            texcoordData[8:10])
        self.paletteIndex = unpack('B', texcoordData[2:3])[0] & 0xf
        self.texturePage = unpack('B', texcoordData[6:7])[0] & 0x3
        self.unknown2_4 = (unpack('B', texcoordData[2:3])[0] >> 4) & 0xf
        self.unknown3 = unpack('B', texcoordData[3:4])[0]
        self.unknown6_2 = (unpack('B', texcoordData[6:7])[0] >> 2) & 0x3f
        self.unknown4 = unpack('B', texcoordData[7:8])[0]
        (val1, tx) = unpack('BB', terrainCoordsData)
        tz = val1 >> 1
        tlvl = val1 & 1
        self.terrainCoords = (tx, tz, tlvl)
        
        vis = unpack('H', visangle)[0]
        self.visible_angles = [ (vis >> (15-x)) & 1 for x in range(16) ]
        return self
    
    def vertices(self):
        for index in 'ABC':
            yield getattr(self, index)

class TriangleUntex(object):
    def from_data(self, pointData, visangle, unknown5=None):
        self.A = VertexUntex(
            short3_t.from_buffer_copy(pointData[0:6]).toTuple(),
        )
        self.B = VertexUntex(
            short3_t.from_buffer_copy(pointData[6:12]).toTuple(),
        )
        self.C = VertexUntex(
            short3_t.from_buffer_copy(pointData[12:18]).toTuple(),
        )
        self.unknown5 = unknown5
        
        vis = unpack('H', visangle)[0]
        self.visible_angles = [ (vis >> (15-x)) & 1 for x in range(16) ]
        return self
    
    def vertices(self):
        for index in 'ABC':
            yield getattr(self, index)

class QuadTex(object):
    def from_data(self, pointData, visangle, normalData=None, texcoordData=None, unknown5=None, terrainCoordsData=None):
        self.A = VertexTex(
            short3_t.from_buffer_copy(pointData[0:6]).toTuple(),
            normalData[0:6],
            texcoordData[0:2])
        self.B = VertexTex(
            short3_t.from_buffer_copy(pointData[6:12]).toTuple(),
            normalData[6:12],
            texcoordData[4:6])
        self.C = VertexTex(
            short3_t.from_buffer_copy(pointData[12:18]).toTuple(),
            normalData[12:18],
            texcoordData[8:10])
        self.D = VertexTex(
            short3_t.from_buffer_copy(pointData[18:24]).toTuple(),
            normalData[18:24],
            texcoordData[10:12])
        self.paletteIndex = unpack('B', texcoordData[2:3])[0] & 0xf
        self.texturePage = unpack('B', texcoordData[6:7])[0] & 0x3
        self.unknown2_4 = (unpack('B', texcoordData[2:3])[0] >> 4) & 0xf
        self.unknown3 = unpack('B', texcoordData[3:4])[0]
        self.unknown6_2 = (unpack('B', texcoordData[6:7])[0] >> 2) & 0x3f
        self.unknown4 = unpack('B', texcoordData[7:8])[0]
        (tyz, tx) = unpack('BB', terrainCoordsData)
        self.terrainCoords = (tx, tyz >> 1, tyz & 0x01)
        
        vis = unpack('H', visangle)[0]
        self.visible_angles = [ (vis >> (15-x)) & 1 for x in range(16) ]
        return self

    def vertices(self):
        for index in 'ABCD':
            yield getattr(self, index)


class QuadUntex(object):
    def from_data(self, pointData, visangle, normalData=None, texcoordData=None, unknown5=None, terrainCoordsData=None):
        self.A = VertexUntex(
            short3_t.from_buffer_copy(pointData[0:6]).toTuple(),
        )
        self.B = VertexUntex(
            short3_t.from_buffer_copy(pointData[6:12]).toTuple(),
        )
        self.C = VertexUntex(
            short3_t.from_buffer_copy(pointData[12:18]).toTuple(),
        )
        self.D = VertexUntex(
            short3_t.from_buffer_copy(pointData[18:24]).toTuple(),
        )
        self.unknown5 = unknown5
        
        vis = unpack('H', visangle)[0]
        self.visible_angles = [ (vis >> (15-x)) & 1 for x in range(16) ]
        return self

    def vertices(self):
        for index in 'ABCD':
            yield getattr(self, index)


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

class Tile(object):
    def __init__(self, tileData):
        val0 = unpack('B', tileData[0:1])[0]
        self.surfaceType = val0 & 0x3f
        self.unknown0_6 = (val0 >> 6) & 0x3
        self.unknown1 = unpack('B', tileData[1:2])[0]
        self.height = unpack('B', tileData[2:3])[0]        # in half-tiles
        val3 = unpack('B', tileData[3:4])[0]
        self.slopeHeight = val3 & 0x1f
        self.depth = (val3 >> 5) & 0x7
        self.slopeType = unpack('B', tileData[4:5])[0]
        self.unknown5 = unpack('B', tileData[5:6])[0]
        val6 = unpack('B', tileData[6:7])[0]
        self.cantCursor = val6 & 1
        self.cantWalk = (val6 >> 1) & 1
        self.unknown6_2 = (val6 >> 2) & 0x3f

        # bits vs rotation flags:
        # 0 = ne bottom
        # 1 = se bottom
        # 2 = sw bottom
        # 3 = nw bottom
        # 4 = ne top
        # 5 = se top
        # 6 = sw top
        # 7 = nw top
        self.rotationFlags = unpack('B', tileData[7:8])[0]

class Terrain(object):
    def __init__(self, terrainData):
        self.tiles = []
        (sizeX, sizeZ) = unpack('2B', terrainData[0:2])
        self.size = (sizeX, sizeZ)
        #print("terrain size", sizeX, sizeZ)
        offset = 2
        for y in range(2):
            level = []
            for z in range(sizeZ):
                row = []
                for x in range(sizeX):
                    tileData = terrainData[offset:offset+8]
                    tile = Tile(tileData)
                    #print('tile', y, x, z, tile.height)
                    row.append(tile)
                    offset += 8
                level.append(row)
            self.tiles.append(level)
            # Skip to second level of terrain data
            offset = 2 + 8 * 256

class Map(object):
    def __init__(self):
        self.texture = Texture_File()
        self.resources = Resources()
        self.situations = []
        self.items = {}

    # check.  calls read()
    def read(self, gnspath):
        self.readGNS(gnspath)
        self.setSituation(0)
        
        self.texture.read(self.textureFiles)
        self.resources.read(self.resourceFiles)
        self.readPolygons()

        self.color_palettes = [
            [RGBA5551.from_buffer_copy(paletteData[i*2:i*2+2]).toTuple() for i in range(16)]
            for paletteData in self.resources.get_color_palettes()
        ]
        self.gray_palettes = [
            [RGBA5551.from_buffer_copy(paletteData[i*2:i*2+2]).toTuple() for i in range(16)]
            for paletteData in self.resources.get_gray_palettes()
        ]

        self.dir_light_rgb = [l for l in self.resources.get_dir_light_rgb()]
        self.dir_light_norm = [l for l in self.resources.get_dir_light_norm()]
        self.amb_light_rgb = self.resources.get_amb_light_rgb()
        self.background = self.resources.get_background()
        self.terrain = Terrain(self.resources.get_terrain())

        # expand the 8-bits into separate 4-bits into an image double array
        # this isn't grey, it's indexed into one of the 16 palettes.
        self.textureIndexedData = []       # [y][x] in [0,15] integers
        for y in range(1024):
            dstrow = []
            for x in range(128):
                i = x + y * 128
                pair = unpack('B', self.texture.data[i:i+1])[0]
                pix1 = (pair >> 0) & 0xf
                pix2 = (pair >> 4) & 0xf
                dstrow.append(pix1)
                dstrow.append(pix2)
            self.textureIndexedData.append(dstrow)
        
        return self

    def readGNS(self, file_path):
        mapNum = int(file_path[-7:-4])
        file = open(file_path, 'rb')
        mapdir = os.path.dirname(file_path)
        situations = {}
        for lineNo in range(0x7fffffff): # or infinity or whatever.  why can't python just count integers without importing from another library?
            sit = readStruct(file, Situation)
            if sit.resourceType == RESOURCE_EOF:
                break
            readStruct(file, SituationEx)    # read? skip?
            resFilePath = os.path.join(mapdir, gnslines[(mapNum, lineNo)])
            situations[sit.toTuple()] = True
            if sit.resourceType == RESOURCE_TEXTURE:
                self.items[(sit.index1, sit.arrange, sit.time, sit.weather, 'tex')] = resFilePath
            else:
                self.items[(sit.index1, sit.arrange, sit.time, sit.weather, 'res')] = resFilePath
        self.situations = sorted(situations.keys())
        file.close()

    def getTextureFiles(self, sitIndex):
        s = Situation(*self.situations[sitIndex])
        found = []
        for key in [
            (s.index1, s.arrange, s.time, s.weather, 'tex'),
            (s.index1, s.arrange, TIME_0, WEATHER_0, 'tex'),
            (s.index1, ARRANGE_0, TIME_0, WEATHER_0, 'tex'),
            (INDEX1_70, ARRANGE_0, TIME_0, WEATHER_0, 'tex'),
            (INDEX1_30, ARRANGE_0, TIME_0, WEATHER_0, 'tex'),
            (INDEX1_22, ARRANGE_0, TIME_0, WEATHER_0, 'tex'),
        ]:
            if key in self.items and self.items[key] not in found:
                found.append(self.items[key])
        return found

    def getResourceFiles(self, sitIndex):
        s = Situation(*self.situations[sitIndex])
        found = []
        for key in [
            (s.index1, s.arrange, s.time, s.weather, 'res'),
            (s.index1, s.arrange, TIME_0, WEATHER_0, 'res'),
            (s.index1, ARRANGE_0, TIME_0, WEATHER_0, 'res'),
            (INDEX1_70, ARRANGE_0, TIME_0, WEATHER_0, 'res'),
            (INDEX1_30, ARRANGE_0, TIME_0, WEATHER_0, 'res'),
            (INDEX1_22, ARRANGE_0, TIME_0, WEATHER_0, 'res'),
        ]:
            if key in self.items and self.items[key] not in found:
                found.append(self.items[key])
        return found

    # check.
    def setSituation(self, sitIndex):
        self.sitIndex = sitIndex % len(self.situations)
        self.textureFiles = self.getTextureFiles(self.sitIndex)
        self.resourceFiles = self.getResourceFiles(self.sitIndex)
        self.resources = Resources()
        # how often is this more than 1?
        print('self.textureFiles', self.textureFiles)
        print('self.resourceFiles', self.resourceFiles)

    # check.
    def readPolygons(self):
        data = self.resources.chunks[0x10].chunks[0x10]
        ofs = 0
        def read(cl):
            nonlocal ofs
            res = cl.from_buffer_copy(data[ofs:ofs+sizeof(cl)])
            ofs += sizeof(cl)
            return res
        
        hdr = read(MeshHeader)
        triTexVtxs = read(short3_t * (3 * hdr.numTriTex))
        quadTexVtxs = read(short3_t * (4 * hdr.numQuadTex))
        triUntexVtxs = read(short3_t * (3 * hdr.numTriUntex))
        quadUntexVtxs = read(short3_t * (4 * hdr.numQuadUntex))
        triTexNormals = read(Normal * (3 * hdr.numTriTex))
        quadTexNormals = read(Normal * (4 * hdr.numQuadTex))
        triTexFaces = read(TriTexFace * hdr.numTriTex)
        quadTexFaces = read(QuadTexFace * hdr.numQuadTex)
        triUntexUnknowns = read(c_uint32 * hdr.numTriUntex) # then comes unknown 4 bytes per untex-tri
        quadUntexUnknowns = read(c_uint32 * hdr.numQuadUntex) # then comes unknown 4 bytes per untex-quad
        triTexTilePos = read(TilePos * hdr.numTriTex) # then comes terrain info 2 bytes per tex-tri
        quadTexTilePos = read(TilePos * hdr.numQuadTex) # then comes terrain info 2 bytes per tex-quad
        # and that's it from chunk # 0x10

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

        """
        self.polygonTriTex = []
        for i in range(hdr.numTriTex):
            self.polygonTriTex.append(TriangleTex().from_data(
                triTexVtxs[3*i:3*i+3],
            ))
        """
        self.polygons = (
                  list(self.getTriTexs(hdr, data))
                + list(self.getQuadTexs(hdr, data))
                + list(self.getTriUntexs(hdr, data))
                + list(self.getQuadUntexs(hdr, data)))

    # check.
    def getTriTexs(self, hdr, data):
        pointData = self.resources.get_tex_3gon_xyz(hdr, data)
        normalData = self.resources.get_tex_3gon_norm(hdr, data)
        tcData = self.resources.get_tex_3gon_uv(hdr, data)
        terrainData = self.resources.get_tex_3gon_terrain_coords(hdr, data)
        visangles = self.resources.get_tex_3gon_vis()
        for pointData, visangle, normalData, texcoordData, terrainCoordsData in zip(pointData, visangles, normalData, tcData, terrainData):
            polygon = TriangleTex().from_data(pointData, visangle, normalData, texcoordData, terrainCoordsData=terrainCoordsData)
            yield polygon

    # check.
    def getQuadTexs(self, hdr, data):
        points = self.resources.get_tex_4gon_xyz(hdr, data)
        normalData = self.resources.get_tex_4gon_norm(hdr, data)
        tcData = self.resources.get_tex_4gon_uv(hdr, data)
        terrainData = self.resources.get_tex_4gon_terrain_coords(hdr, data)
        visangles = self.resources.get_tex_4gon_vis()
        for pointData, visangle, normalData, texcoordData, terrainCoordsData in zip(points, visangles, normalData, tcData, terrainData):
            polygon = QuadTex().from_data(pointData, visangle, normalData, texcoordData, terrainCoordsData=terrainCoordsData)
            yield polygon

    # check.
    def getTriUntexs(self, hdr, data):
        points = self.resources.get_untex_3gon_xyz(hdr, data)
        unknowns = self.resources.get_untex_3gon_unknown(hdr, data)
        visangles = self.resources.get_untex_3gon_vis()
        for pointData, visangle, unknown in zip(points, visangles, unknowns):
            polygon = TriangleUntex().from_data(pointData, visangle, unknown5=unknown)
            yield polygon

    # check.
    def getQuadUntexs(self, hdr, data):
        points = self.resources.get_untex_4gon_xyz(hdr, data)
        unknowns = self.resources.get_untex_4gon_unknown(hdr, data)
        visangles = self.resources.get_untex_4gon_vis()
        for pointData, visangle, unknown in zip(points, visangles, unknowns):
            polygon = QuadUntex().from_data(pointData, visangle, unknown5=unknown)
            yield polygon

    def write(self):
        #self.texture.write()
        self.resources.write()

    def put_texture(self, texture):
        texture_data = ''
        for y in range(1024):
            for x in range(128):
                pix1 = texture[y][x*2]
                pix2 = texture[y][x*2 + 1]
                pair = pack('B', (pix1 << 0) | (pix2 << 4))
                texture_data += pair
        self.texture.write(texture_data)

    def put_terrain(self, terrain):
        max_x = len(terrain.tiles[0][0])
        max_z = len(terrain.tiles[0])
        terrainData = pack('BB', max_x, max_z)
        for level in terrain.tiles:
            for row in level:
                for tile in row:
                    terrainData += (''
                        + pack('B', (tile.unknown0_6 << 6) | tile.surfaceType)
                        + pack('B', tile.unknown1)
                        + pack('B', tile.height)
                        + pack('B', (tile.depth << 5) | tile.slopeHeight)
                        + pack('B', tile.slopeType)
                        + pack('B', tile.unknown5)
                        + pack('B', (tile.unknown4 << 2) | (tile.cantWalk << 1) | tile.cantCursor)
                        + pack('B', tile.unknown6_2)
                    )
            # Skip to second level of terrain data
            terrainData += '\x00' * (8 * 256 - 8 * max_x * max_z)
        self.resources.put_terrain(terrainData)

    def put_visible_angles(self, polygons):
        self.resources.put_visible_angles(polygons)

    # TODO make this a method of the poly
    def vertexesForPoly(self, poly):
        if hasattr(poly, 'D'):
            return [poly.A, poly.C, poly.D, poly.B]        # cw => ccw and tristrip -> quad
        return [poly.A, poly.C, poly.B]                    # cw front-face => ccw front-face

################################ import_gns ################################

# https://blender.stackexchange.com/a/239948
def find_nodes_by_type(material, node_type):
    node_list = []
    if material.use_nodes and material.node_tree:
            for n in material.node_tree.nodes:
                if n.type == node_type:
                    node_list.append(n)
    return node_list

def load(context,
         filepath,
         *,
         global_scale_x=28.0,
         global_scale_y=24.0,
         global_scale_z=28.0,
         relpath=None,
         global_matrix=None
         ):
    with ProgressReport(context.window_manager) as progress:
        from bpy_extras import node_shader_utils

        progress.enter_substeps(1, "Importing GNS %r..." % filepath)

        filename = os.path.splitext((os.path.basename(filepath)))[0]

        if global_matrix is None:
            global_matrix = mathutils.Matrix()

        verts_loc = []
        verts_nor = []
        verts_tex = []
        faces = []  # tuples of the faces
        material_libs = set()  # filenames to material libs this OBJ uses
        vertex_groups = {}

        unique_materials = {}

        progress.enter_substeps(3, "Parsing GNS file...")

        map = Map().read(filepath)

        # deselect all
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        newObjects = []  # put new objects here


        ### make the material for textured faces

        # for now lets have 1 material to parallel ganesha / my obj exporter
        # later I can do 1 material per palette or something

        def makeTexMat(name, image):
            # get image ...
            # https://blender.stackexchange.com/questions/643/is-it-possible-to-create-image-data-and-save-to-a-file-from-a-script
            matWTex = unique_materials[name] = bpy.data.materials.new(name)
            matWTexWrap = node_shader_utils.PrincipledBSDFWrapper(matWTex, is_readonly=False)
            matWTexWrap.use_nodes = True
            matWTexWrap.base_color_texture.image = image
            matWTexWrap.base_color_texture.texcoords = 'UV'
            # setup transparency
            # link texture alpha channel to Principled BSDF material
            # https://blender.stackexchange.com/a/239948
            matWTex.node_tree.links.new(
                find_nodes_by_type(matWTex, 'BSDF_PRINCIPLED')[0].inputs['Alpha'],
                find_nodes_by_type(matWTex, 'TEX_IMAGE')[0].outputs['Alpha'])
            matWTexWrap.ior = 1.
            matWTexWrap.alpha = 1.
            #matWTex.blend_method = 'BLEND'  #the .obj loader has BLEND, but it makes everything semitransparent to the background grid
            matWTex.blend_method = 'CLIP'    # ... and so far neither BLEND nor CLIP makes the tree transparent

            # default specular is 1, which is shiny, which is ugly
            matWTexWrap.specular = 0.
            matWTexWrap.specular_tint = 0.
            matWTexWrap.roughness = 0.

        # here's the indexed texture, though it's not attached to anything
        matTexIndexedImg = bpy.data.images.new('GNS Tex Indexed', width=256, height=1024)
        matTexIndexedImg.pixels = [
            ch
            for row in map.textureIndexedData
            for colorIndex in row
            for ch in (
                colorIndex/15.,
                colorIndex/15.,
                colorIndex/15.,
                1.
            )
        ]
        matTexIndexedName = 'GNS Mat Tex Indexed'
        makeTexMat(matTexIndexedName, matTexIndexedImg)


        # write out each individual 16 palettes
        imagePerPal = [None] * len(map.color_palettes)
        matTexNamePerPal = [None] * len(map.color_palettes)
        for (i, palette) in enumerate(map.color_palettes):
            imagePerPal[i] = bpy.data.images.new('GNS Tex Pal '+str(i), width=256, height=1024)
            imagePerPal[i].pixels = [
                ch
                for row in map.textureIndexedData
                for colorIndex in row
                for ch in palette[colorIndex]
            ]
            matTexNamePerPal[i] = 'GNS Mat Tex Pal '+str(i)
            makeTexMat(matTexNamePerPal[i], imagePerPal[i])

        # TODO just write a single greyscale image,
        # and write the 16 palettes
        # and set up Graph Editor for dynamically picking the palette


        ### make the material for untextured faces

        matWOTexName = 'GNS Material Untextured'
        matWOTex = unique_materials[matWOTexName] = bpy.data.materials.new(matWOTexName)
        matWOTexWrap = node_shader_utils.PrincipledBSDFWrapper(matWOTex, is_readonly=False)
        matWOTexWrap.use_nodes = True
        matWOTexWrap.specular = 0
        matWOTexWrap.base_color = (0., 0., 0.)


        ### make the mesh

        material_mapping = {name: i for i, name in enumerate(unique_materials)}
        materials = [None] * len(unique_materials)
        for name, index in material_mapping.items():
            materials[index] = unique_materials[name]

        mesh = bpy.data.meshes.new(filename)
        for material in materials:
            mesh.materials.append(material)

        vi = 0
        vti = 0
        for s in map.polygons:
            V = map.vertexesForPoly(s)
            n = len(V)
            for v in V:
                vtxHasTexCoord = hasattr(v, 'normal')
                verts_loc.append(v.point)

                if vtxHasTexCoord:
                    verts_tex.append((
                        v.texcoord[0] / 256.,
                        (s.texturePage + v.texcoord[1] / 256.) / 4.
                    ))
                    verts_nor.append(v.normal)
                else:
                    # if I exclude the texcoords and normals on the faces that don't use them then I get this error in blender:
                    #  Error: Array length mismatch (got 6615, expected more)
                    # should I put the non-texcoord/normal'd faces in a separate mesh?
                    # TODO give them their own material
                    verts_tex.append((0,0))
                    verts_nor.append((0,0,0))

            # turn all polys into fans
            for i in range(1,n-1):
                face_vert_loc_indices = [vi+0, vi+i, vi+i+1]
                #if vtxHasTexCoord:
                face_vert_nor_indices = [vti+0, vti+i, vti+i+1]
                face_vert_tex_indices = [vti+0, vti+i, vti+i+1]
                faces.append((
                    face_vert_loc_indices,
                    face_vert_nor_indices,
                    face_vert_tex_indices,
                    matTexNamePerPal[s.paletteIndex] if vtxHasTexCoord else matWOTexName,
                    None, # used to be smooth ...
                    None, # used to be object key?
                    [],  # If non-empty, that face is a Blender-invalid ngon (holes...), need a mutable object for that...
                ))
            vi+=n
            #if vtxHasTexCoord:
            vti+=n

        loops_vert_idx = tuple(vidx for (face_vert_loc_indices, _, _, _, _, _, _) in faces for vidx in face_vert_loc_indices)
        print('len faces', len(faces))
        print('len loops_vert_idx', len(loops_vert_idx))

        fgon_edges = set()
        tot_loops = 3 * len(faces)

        mesh.polygons.add(len(faces))
        mesh.loops.add(tot_loops)
        mesh.vertices.add(len(verts_loc))

        mesh.vertices.foreach_set("co", unpack_list(verts_loc))

        faces_loop_start = []
        lidx = 0
        for f in faces:
            face_vert_loc_indices = f[0]
            nbr_vidx = len(face_vert_loc_indices)
            faces_loop_start.append(lidx)
            lidx += nbr_vidx
        faces_loop_total = tuple(len(face_vert_loc_indices) for (face_vert_loc_indices, _, _, _, _, _, _) in faces)

        print('len faces', len(faces))
        print('len loops_vert_idx', len(loops_vert_idx))

        mesh.loops.foreach_set("vertex_index", loops_vert_idx)
        mesh.polygons.foreach_set("loop_start", faces_loop_start)
        mesh.polygons.foreach_set("loop_total", faces_loop_total)

        faces_ma_index = tuple(material_mapping[context_material] for (_, _, _, context_material, _, _, _) in faces)
        mesh.polygons.foreach_set("material_index", faces_ma_index)

        mesh.polygons.foreach_set("use_smooth", [False] * len(faces))

        if verts_nor and mesh.loops:
            mesh.create_normals_split()
            loops_nor = tuple(no for (_, face_vert_nor_indices, _, _, _, _, _) in faces
                                 for face_noidx in face_vert_nor_indices
                                 for no in verts_nor[face_noidx])
            mesh.loops.foreach_set("normal", loops_nor)

        if verts_tex and mesh.polygons:
            mesh.uv_layers.new(do_init=False)
            loops_uv = tuple(uv for (_, _, face_vert_tex_indices, _, _, _, _) in faces
                                for face_uvidx in face_vert_tex_indices
                                for uv in verts_tex[face_uvidx])
            mesh.uv_layers[0].data.foreach_set("uv", loops_uv)

        mesh.validate(clean_customdata=False)  # *Very* important to not remove lnors here!
        mesh.update()

        if verts_nor:
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

        for group_name, group_indices in vertex_groups.items():
            group = meshObj.vertex_groups.new(name=group_name.decode('utf-8', "replace"))
            group.add(group_indices, 1.0, 'REPLACE')


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
            for z in range(map.terrain.size[1]):
                for x in range(map.terrain.size[0]):
                    tile = map.terrain.tiles[y][z][x]
                    vi = len(tmeshVtxs)
                    tmeshFaces.append([vi+0, vi+1, vi+2, vi+3])
                    for (i, q) in enumerate(quadVtxs):
                        tmeshVtxs.append((
                            x + .5 + q[0],
                            -.5 * (tile.height + (tile.slopeHeight if tile.slopeType in liftPerVertPerSlopeType[i] else 0)),
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
            'rotationFlags',
            'unknown0_6',
            'unknown1',
            'unknown5',
            'unknown6_2'
            # via terrain mesh
            #'height',
            #'slopeType',
            #'slopeHeight',
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
                bm.faces[i][tags[name]] = tile.__dict__[name]
        if bpy.context.mode == 'EDIT_MESH':
            bm.updated_edit_mesh(tmeshObj.data)
        else:
            bm.to_mesh(tmeshObj.data)
        bm.free()


        # directional lights
        # https://stackoverflow.com/questions/17355617/can-you-add-a-light-source-in-blender-using-python
        for i in range(3):
            lightName = 'GNS Light '+str(i)
            lightData = bpy.data.lights.new(name=lightName, type='SUN')
            lightData.energy = 20       # ?
            lightData.color = map.dir_light_rgb[i]
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
            # calculate lightObj Euler angles by dir_light_norm
            # TODO figure out which rotates which...
            dir = map.dir_light_norm[i]
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
        world = bpy.data.worlds['World']
        background = world.node_tree.nodes['Background']
        background.inputs[0].default_value[:3] = map.amb_light_rgb
        background.inputs[1].default_value = 5.

        # ... but the most common way of doing a skybox in blender is ...
        # ... overriding the world background
        # so ... what to do.
        # just put a big sphere around the outside?
        #  but how come when I do this, the sphere backface-culls, even when backface-culling is disabled?
        #  why does alpha not work when alpha-clipping or alpha-blending is enabled?
        #  and why did the goblin turn on the stove?
        # https://blender.stackexchange.com/questions/39409/how-can-i-make-the-outside-of-a-sphere-transparent

        ### Create new objects
        view_layer = context.view_layer
        collection = view_layer.active_layer_collection.collection
        for obj in newObjects:
            collection.objects.link(obj)
            obj.select_set(True)

            # apply up/fwd transform
            # setting this override any previous location / rotation_euler set
            # how can we just apply this transform to the previous transform?
            # maybe https://blender.stackexchange.com/questions/27667/incorrect-matrix-world-after-transformation ?
            # ... says you gotta call view_layer.update() after setting location / rotation_euler / scale ...
            # ... sooo ... what order to set all the tranforms ...
            #obj.matrix_world = global_matrix

        view_layer.update()


        progress.leave_substeps("Done.")
        progress.leave_substeps("Finished importing: %r" % filepath)

    return {'FINISHED'}
