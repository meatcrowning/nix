init()
{
    level thread restore_fov();
}

restore_fov()
{
    // The engine resets FOV during map initialization, after reading the config.
    wait 0.05;
    fov = getdvarfloat( "mw2_sp_fov" );
    scale = getdvarfloat( "mw2_sp_fovScale" );
    if ( fov >= 1 && fov <= 160 )
        adddebugcommand( "cg_fov " + fov + "\n" );
    if ( scale >= 0.2 && scale <= 2 )
        adddebugcommand( "cg_fovScale " + scale + "\n" );
}
