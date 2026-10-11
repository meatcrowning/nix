/* The viewer's private library/theme settings must not escape into editors,
 * help viewers or settings. Restore the caller's environment in every GDK
 * launch context, including those created internally by gtk_show_uri(). */
static void
viewer_restore_launch_environment(GAppLaunchContext *context)
{
    const char prefix[] = "_UNITY_VIEWER_HOST_";
    gchar **names = g_listenv();
    for (gchar **p = names; *p; p++) {
        if (!g_str_has_prefix(*p, prefix)) continue;
        const char *name = *p + sizeof(prefix) - 1;
        const char *value = g_getenv(*p);
        if (g_str_has_prefix(value, "set:"))
            g_app_launch_context_setenv(context, name, value + 4);
        else
            g_app_launch_context_unsetenv(context, name);
        g_app_launch_context_unsetenv(context, *p);
    }
    g_strfreev(names);
}
