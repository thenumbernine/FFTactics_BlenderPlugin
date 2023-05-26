import os.path
from ctypes import *

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
