# Final Fantasy Tactics Blender Importer

This is modified heavily from the JustinMarshall98 Ganesha Python version, which itself was modified from the Gomtuu Ganesha Python version.
It was convenient that Blender plugins are written in Python.
It's also borrowing a lot of wisdom from the C# port, GaneshaDx.

![example](ex3.png)

## Installing

To get it working, copy the folder structure into your Blender user path.
If you don't know where that is then follow this link:

https://docs.blender.org/manual/en/latest/advanced/blender_directory_layout.html

Once it is copied, next go to Edit -> Preferences -> Add-Ons, then scroll down or filter by the word 'GNS', and you should see the plug-in:

![step 1](ex1.png)

Click the checkbox and you should now find a new option under File -> Import:

![step 2](ex2.png)

## Progress

The mesh is importing.

The 3 directional lights' colors are importing.
The directions are still meh.

The map ambient light is assigned to the world background color.

The terrain tiles are imported and custom per-face attributes are stored.  These can be accessed from 'Geometry Nodes' -> 'Face' -> scroll right in list of face attributes to see all the extra custom ones.

TODO:
- separate the indexed-texture from the palettes, and make palettes somehow easily swappable in blender.
- I'm handling ambient via assigning it to the world background color.  is this a good thing?
- preserve quads? right now it triangulates everything, but GNS supports tris and quads.
- light directions as blender-sun-light rotations, and just figuring out blender's transform system.
- ... how to organize all transforms?  should I work in mesh vertex coords so blocks are 28x24x28?  should I work in tile coords?  where to put the transforms?  z-up vs y-up?  matrix local vs matrix global vs location rotation euler vs scale...
- background gradients.  skybox?  sky-sphere?  camera-fixed billboard?
- should terrain custom face attributes be integers or strings?  would be nice to set them to dropdowns for selecting enumerations.
- exporting.

## Sources:

- https://github.com/JustinMarshall98/Ganesha
- https://github.com/Garmichael/GaneshaDx
