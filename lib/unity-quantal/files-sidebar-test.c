/* A synthetic model with Nautilus's exact column ABI, inside the isolated
 * Quantal runtime. No real file-manager window, phone, or host bus. */
#include "files-sidebar.c"

typedef struct { GtkListStore parent; } NautilusShortcutsModel;
typedef struct { GtkListStoreClass parent; } NautilusShortcutsModelClass;
G_DEFINE_TYPE(NautilusShortcutsModel, nautilus_shortcuts_model, GTK_TYPE_LIST_STORE)
static void nautilus_shortcuts_model_class_init(NautilusShortcutsModelClass *klass) { (void)klass; }
static void nautilus_shortcuts_model_init(NautilusShortcutsModel *model)
{
    GType types[] = { G_TYPE_INT, G_TYPE_STRING, G_TYPE_OBJECT, G_TYPE_OBJECT,
        G_TYPE_OBJECT, G_TYPE_STRING, GDK_TYPE_PIXBUF, G_TYPE_INT, G_TYPE_BOOLEAN,
        G_TYPE_BOOLEAN, G_TYPE_BOOLEAN, G_TYPE_STRING, GDK_TYPE_PIXBUF,
        G_TYPE_INT, G_TYPE_STRING };
    gtk_list_store_set_column_types(GTK_LIST_STORE(model), 15, types);
}
static gint unchanged(GtkTreeModel *model, GtkTreeIter *a, GtkTreeIter *b, gpointer data)
{ (void)model; (void)a; (void)b; (void)data; return 0; }
static void fill(GtkListStore *store)
{
    GtkTreeIter iter;
    for (int section = 0; section < 4; section++) {
        gtk_list_store_insert_with_values(store, &iter, -1, ROW, 4, SECTION, section, -1);
        gtk_list_store_insert_with_values(store, &iter, -1, ROW, 0, SECTION, section,
                                         NAME, "ordinary", URI, "file:///tmp", -1);
    }
    while (g_main_context_iteration(NULL, FALSE));
}
int main(int argc, char **argv)
{
    gtk_init(&argc, &argv);
    GtkListStore *store = g_object_new(nautilus_shortcuts_model_get_type(), NULL);
    GtkTreeModel *model = GTK_TREE_MODEL(store);
    gtk_tree_sortable_set_sort_func(GTK_TREE_SORTABLE(store), NAME, unchanged, NULL, NULL);
    gtk_tree_sortable_set_sort_column_id(GTK_TREE_SORTABLE(store), NAME, GTK_SORT_ASCENDING);
    GtkWidget *view = gtk_tree_view_new();
    g_object_ref_sink(view);
    gtk_tree_view_set_model(GTK_TREE_VIEW(view), model);
    for (int pass = 0; pass < 2; pass++) {
        fill(store);
        int sections[] = {2, 0, 1, 3}, index = 0, phones = 0;
        GtkTreeIter iter;
        for (gboolean valid = gtk_tree_model_get_iter_first(model, &iter); valid;
             valid = gtk_tree_model_iter_next(model, &iter)) {
            int section, row;
            gtk_tree_model_get(model, &iter, SECTION, &section, ROW, &row, -1);
            if (row == 4) { g_assert_cmpint(index, <, 4); g_assert_cmpint(section, ==, sections[index++]); }
            if (is_phone(model, &iter)) {
                phones++;
                g_assert_cmpint(section, ==, 3);
                gtk_tree_selection_select_iter(gtk_tree_view_get_selection(GTK_TREE_VIEW(view)), &iter);
                g_assert(selected_phone(view));
                g_assert(popup(view, NULL));
                GdkEventKey event = { .keyval = GDK_KEY_Return };
                /* No command is set, so this verifies consumption without launching. */
                g_unsetenv("UNITY_FILES_PHONE_COMMAND");
                g_assert(key(view, &event, NULL));
            }
        }
        g_assert_cmpint(index, ==, 4);
        g_assert_cmpint(phones, ==, 1);
        gtk_list_store_clear(store);
    }
    gtk_widget_destroy(view);
    g_object_unref(view);
    g_object_unref(store);
    g_print("PASS: Computer first; one phone in Network after sidebar rebuild; phone activation intercepted\n");
    return 0;
}
