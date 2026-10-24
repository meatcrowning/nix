/* Adapt only the original NautilusShortcutsModel; keep its row ABI and
 * comparator for ordering within sections. GTK resolves from Quantal. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <gtk/gtk.h>
#include <string.h>

enum { ROW = 0, URI = 1, NAME = 5, ICON = 6, NO_EJECT = 9,
       BOOKMARK = 10, TOOLTIP = 11, SECTION = 13 };
#define PHONE_URI "unity-phone:///"

typedef struct {
    GtkTreeIterCompareFunc compare;
    gpointer data;
    GDestroyNotify destroy;
} Sort;

static gboolean sidebar(GtkTreeModel *model)
{
    return model && strcmp(G_OBJECT_TYPE_NAME(model), "NautilusShortcutsModel") == 0
        && gtk_tree_model_get_n_columns(model) == 15;
}

static gint compare(GtkTreeModel *model, GtkTreeIter *a, GtkTreeIter *b, gpointer data)
{
    Sort *sort = data;
    int sa, sb, ra, rb;
    const int rank[] = { 1, 2, 0, 3 }; /* Computer, Devices, Bookmarks, Network */
    gtk_tree_model_get(model, a, SECTION, &sa, ROW, &ra, -1);
    gtk_tree_model_get(model, b, SECTION, &sb, ROW, &rb, -1);
    if (sa >= 0 && sa < 4 && sb >= 0 && sb < 4 && sa != sb)
        return rank[sa] - rank[sb];
    if ((ra == 4) != (rb == 4))
        return ra == 4 ? -1 : 1;
    return sort->compare(model, a, b, sort->data);
}

static void free_sort(gpointer data)
{
    Sort *sort = data;
    if (sort->destroy) sort->destroy(sort->data);
    g_free(sort);
}

void gtk_tree_sortable_set_sort_func(GtkTreeSortable *model, gint column,
                                   GtkTreeIterCompareFunc func, gpointer data,
                                   GDestroyNotify destroy)
{
    void (*original)(GtkTreeSortable *, gint, GtkTreeIterCompareFunc, gpointer,
                     GDestroyNotify) = dlsym(RTLD_NEXT, "gtk_tree_sortable_set_sort_func");
    if (sidebar(GTK_TREE_MODEL(model)) && column == NAME) {
        Sort *sort = g_new(Sort, 1);
        *sort = (Sort){ func, data, destroy };
        original(model, column, compare, sort, free_sort);
    } else original(model, column, func, data, destroy);
}

static gboolean is_phone(GtkTreeModel *model, GtkTreeIter *iter)
{
    char *uri = NULL;
    gtk_tree_model_get(model, iter, URI, &uri, -1);
    gboolean result = g_strcmp0(uri, PHONE_URI) == 0;
    g_free(uri);
    return result;
}

static gboolean ensure_phone(gpointer data)
{
    GtkTreeModel *model = data;
    GtkTreeIter iter;
    gboolean found = FALSE;
    for (gboolean valid = gtk_tree_model_get_iter_first(model, &iter); valid;
         valid = gtk_tree_model_iter_next(model, &iter))
        if (is_phone(model, &iter)) { found = TRUE; break; }
    if (!found) {
        GdkPixbuf *icon = gtk_icon_theme_load_icon(gtk_icon_theme_get_default(),
                                                  "phone", 16, 0, NULL);
        gtk_list_store_insert_with_values(GTK_LIST_STORE(model), &iter, -1,
            ROW, 0, URI, PHONE_URI, NAME, "Galaxy Phone", ICON, icon,
            SECTION, 3, NO_EJECT, TRUE, BOOKMARK, TRUE,
            TOOLTIP, "Browse your Galaxy phone with KDE Connect", -1);
        if (icon) g_object_unref(icon);
    }
    g_object_set_data(G_OBJECT(model), "unity-phone-pending", NULL);
    return G_SOURCE_REMOVE;
}

/* Keep GLib references lazy: non-GTK subprocesses inherit this preload. */
static void unref_model(gpointer model)
{
    g_object_unref(model);
}

static void changed(GtkTreeModel *model, GtkTreePath *path, GtkTreeIter *iter, gpointer data)
{
    (void)path; (void)iter; (void)data;
    if (!g_object_get_data(G_OBJECT(model), "unity-phone-pending")) {
        g_object_set_data(G_OBJECT(model), "unity-phone-pending", GINT_TO_POINTER(1));
        g_idle_add_full(G_PRIORITY_DEFAULT_IDLE, ensure_phone, g_object_ref(model), unref_model);
    }
}

static void launch_phone(void)
{
    const char *command = g_getenv("UNITY_FILES_PHONE_COMMAND");
    if (command) {
        GError *error = NULL;
        if (!g_spawn_command_line_async(command, &error)) {
            g_warning("Cannot browse phone: %s", error->message);
            g_error_free(error);
        }
    }
}

static gboolean phone_at(GtkTreeView *view, GdkEventButton *event)
{
    GtkTreePath *path = NULL;
    GtkTreeIter iter;
    GtkTreeModel *model = gtk_tree_view_get_model(view);
    if (event->window != gtk_tree_view_get_bin_window(view) ||
        !gtk_tree_view_get_path_at_pos(view, event->x, event->y, &path, NULL, NULL, NULL))
        return FALSE;
    gboolean result = gtk_tree_model_get_iter(model, &iter, path) && is_phone(model, &iter);
    if (result) gtk_tree_view_set_cursor(view, path, NULL, FALSE);
    gtk_tree_path_free(path);
    return result;
}

static gboolean press(GtkWidget *view, GdkEventButton *event, gpointer data)
{
    (void)data;
    if (!phone_at(GTK_TREE_VIEW(view), event)) return FALSE;
    if (event->button == 2) launch_phone();
    return event->button != 1;
}

static gboolean release(GtkWidget *view, GdkEventButton *event, gpointer data)
{
    (void)data;
    if (!phone_at(GTK_TREE_VIEW(view), event)) return FALSE;
    if (event->button == 1) launch_phone();
    return TRUE;
}

static gboolean selected_phone(GtkWidget *view)
{
    GtkTreeModel *model;
    GtkTreeIter iter;
    return gtk_tree_selection_get_selected(gtk_tree_view_get_selection(GTK_TREE_VIEW(view)),
                                           &model, &iter) && is_phone(model, &iter);
}

static gboolean key(GtkWidget *view, GdkEventKey *event, gpointer data)
{
    (void)data;
    if (!selected_phone(view)) return FALSE;
    if (event->keyval == GDK_KEY_Return || event->keyval == GDK_KEY_KP_Enter ||
        event->keyval == GDK_KEY_space) {
        launch_phone();
        return TRUE;
    }
    return event->keyval == GDK_KEY_Menu || event->keyval == GDK_KEY_F10;
}

static gboolean popup(GtkWidget *view, gpointer data)
{
    (void)data;
    return selected_phone(view);
}

void gtk_tree_view_set_model(GtkTreeView *view, GtkTreeModel *model)
{
    void (*original)(GtkTreeView *, GtkTreeModel *) = dlsym(RTLD_NEXT, "gtk_tree_view_set_model");
    original(view, model);
    if (!sidebar(model) || g_object_get_data(G_OBJECT(view), "unity-sidebar")) return;
    g_object_set_data(G_OBJECT(view), "unity-sidebar", GINT_TO_POINTER(1));
    g_signal_connect(model, "row-inserted", G_CALLBACK(changed), NULL);
    changed(model, NULL, NULL, NULL);
    /* Installed before Nautilus's handlers so a phone click never navigates
     * to an unsupported URI. The host mounts it, then opens the local path. */
    g_signal_connect(view, "button-press-event", G_CALLBACK(press), NULL);
    g_signal_connect(view, "button-release-event", G_CALLBACK(release), NULL);
    g_signal_connect(view, "key-press-event", G_CALLBACK(key), NULL);
    g_signal_connect(view, "popup-menu", G_CALLBACK(popup), NULL);
}
