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

The terrain tiles are imported and custom per-face attributes are stored.  These can be accessed from 'Geometry Nodes' -> 'Face' -> scroll right in list of face attributes to see all the extra custom ones.

The 3 directional lights' colors are imported as sun lights.
The directions are still meh.

The map ambient light is imported as a sun light too, but I know sun light is directional, idk where to set ambient-light in materials in blender... 

The background is imported as a sphere around the map, with gradient material.

TODO:
- Ambient is an extra sun light ... but sun is directional and ambient is not.  How should it be specified?
- preserve quads? right now it triangulates everything, but GNS supports tris and quads.
- light directions as blender-sun-light rotations, and just figuring out blender's transform system.
- ... how to organize all transforms?  should I work in mesh vertex coords so blocks are 28x24x28?  should I work in tile coords?  where to put the transforms?  z-up vs y-up?  matrix local vs matrix global vs location rotation euler vs scale...
- should terrain custom face attributes be integers or strings?  would be nice to set them to dropdowns for selecting enumerations.
- if I'm writing a plugin for blender IO, why not also write a plugin for face-picking that pops up editing the different custom-face attributes?
- preserve situations?  right now it's just reading the first texture from the first situation.
- - instead it could just read in everything, multiple objects / layers / scenes / whatever per map configuration, read and write all at once instead of picking your configuration upon file load.
- exporting.

Design TODO
- make a root obj of the meshObj/tmeshObj/lights
- put meshObj under it with scale (1/28, 1/24, 1/28) so it is proportional to the terrain geom
- put tmeshObj under it with no scale
- give root obj a scale of (1, 24/28, 1) so the horz/vert ratio is correct
- put lightObjs under ... which one ?
- also ambient has to be a light now, or a meshObj mat property?
- make one of these rootObjs' per map state? duplicate meshes? etc?
- eventually map all of a GNS file's resources to objects,
- - then collect these objects under parent objects per-mapstate-configuration.

## Sources:

- https://github.com/JustinMarshall98/Ganesha
- https://github.com/Garmichael/GaneshaDx
