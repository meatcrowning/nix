/* Quantal's generated UDisksObjectProxy signal handlers dereference interface
 * metadata even for interfaces introduced after 2012 (such as NVMe). GIO
 * represents those as generic proxies with NULL metadata. Keep the original
 * handlers for known interfaces and ignore the unknown ones, as newer
 * gdbus-codegen output does. Loaded only by the legacy volume monitor. */
#include <gio/gio.h>

extern GType udisks_object_proxy_get_type(void);
static void (*original_added)(GDBusObject *, GDBusInterface *);
static void (*original_removed)(GDBusObject *, GDBusInterface *);

static void added(GDBusObject *object, GDBusInterface *interface)
{
    if (g_dbus_interface_get_info(interface) && original_added)
        original_added(object, interface);
}

static void removed(GDBusObject *object, GDBusInterface *interface)
{
    if (g_dbus_interface_get_info(interface) && original_removed)
        original_removed(object, interface);
}

__attribute__((constructor)) static void install(void)
{
    /* GLib 2.34 predates automatic type-system initialization. Retain the
     * class reference for the process lifetime so these handlers stay put. */
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS
    g_type_init();
    G_GNUC_END_IGNORE_DEPRECATIONS
    gpointer klass = g_type_class_ref(udisks_object_proxy_get_type());
    GDBusObjectIface *iface = g_type_interface_peek(klass, G_TYPE_DBUS_OBJECT);
    original_added = iface->interface_added;
    original_removed = iface->interface_removed;
    iface->interface_added = added;
    iface->interface_removed = removed;
}
