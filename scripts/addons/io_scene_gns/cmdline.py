#!/usr/bin/env python
# I'm not sure what output format I'm aiming for
import os
import os.path
import argparse
import gns

ap = argparse.ArgumentParser()
ap.add_argument('files', metavar='files', nargs='*')
ap.add_argument('-d', '--dir', help='process all maps in dir')
ap.add_argument('-x', '--hex', action='store_true', help='output struct field values in hex')
ap.add_argument('-v', '--verbose', action='store_true', help='verbose output of all chunk data')
args = ap.parse_args()

if args.hex:
    def bleh(x):
        if not isinstance(x, int):
            return str(x)
        s = f'{x:x}'
        if s[0] == '-':
            return '-0x'+s[1:]
        else:
            return '0x'+s
    intToStr = bleh
    gns.FFTData.intToStr = bleh
else:
    intToStr = gns.FFTData.intToStr

def processMap(fn):
    print('Loading', fn)
    try:
        # load the gns file
        g = gns.GNS(fn)
        
        # print the GNS file records
        for res in g.allRes:
            record = res.record
            print('GNS record, file=', res.filename, str(record), end='')
            if isinstance(res, gns.TexBlob):
                print(' ... texture')
            elif isinstance(res, gns.NonTexBlob):
                print(' ... chunks: '+', '.join([intToStr(i) for i, e in enumerate(res.header.v) if e != 0]))
            else:
                print(' ... unknown')

        if args.verbose:
            # print the chunks in each individual resource file:
            for res in g.allRes:
                print()
                print(res.filename+':')
                if isinstance(res, gns.TexBlob):
                    # TODO output the textures themselves?
                    pass # I hate python
                elif isinstance(res, gns.NonTexBlob):
                    for (i, io) in enumerate(res.chunkIOs):
                        if io != None:
                            print('... chunk '+intToStr(i))
                            print(str(io))
                else:
                    # TODO output a big 'unknown!"
                    pass # I hate python
            
            print()

    #except Exception as e:
    #    print("failed with error", repr(e))
    finally:
        pass # I hate python

def processDir(dirpath):
    fns = []
    for fn in os.listdir(dirpath):
        if os.path.splitext(fn)[1].upper() == '.GNS':
            fns.append(fn)
    fns.sort()
    for fn in fns:
        processMap(os.path.join(dirpath, fn))

if args.dir:
    processDir(args.dir)
else:
    for fn in args.files:
        if os.path.isdir(fn):
            processDir(fn)
        else:
            processMap(fn)

print("DONE")
