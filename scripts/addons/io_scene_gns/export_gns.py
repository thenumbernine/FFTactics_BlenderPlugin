def save(
    context,
    filepath,
    *,
    use_texture=True,
    use_mesh=True,
    use_tiles=True,
    use_colorpals=True,
    use_graypals=True,
    use_lights=True,
    use_visangles=True,
    global_matrix=None,
    path_mode='AUTO'
):

    # ... for which configuration are we saving?
    # how to discern between saving the base cfg/mesh vs saving modified?
    #  always save all?
    #  checkboxes?  int selection?
    # cycle through all collections and look at the names?
    # how about a collection-per-resource-file?
    #  which stores the ext no ... like, the collection name == the resource filename
    #  and then the collections hold objects pertaining to the resources?
    # then we'd have two sets of collectiosn ... one for the map files, and one for the resources
    #  and don't duplicate nodes between them?  somehow?  would require some rearranging for the mesh...

    # first off I gotta load the gns records of what resources are available (right?)
    # ... or should I keep track of that information as well, from the collections?
    if not os.path.exists(filepath):
        raise Exception("currently I can't write new files, just modify old ones.")
    
    from . import gns
    GNS = gns.GNS

    gns = GNS(filepath)

    if use_texture:
        # export textures ... which textures tho? to where?

    return {'FINISHED'}
