/* The separate user menu from the earlier Unity panel, using Quantal widgets
 * and the session's existing settings, locking and logout commands. */
#include "user-menu.h"
#include <gio/gio.h>

typedef struct {
    IndicatorObject parent;
    GtkLabel *label;
    GtkImage *image;
    GtkMenu *menu;
} UserMenu;
typedef IndicatorObjectClass UserMenuClass;
G_DEFINE_TYPE(UserMenu, user_menu, INDICATOR_OBJECT_TYPE)

static GtkLabel *get_label(IndicatorObject *object) { return ((UserMenu *)object)->label; }
static GtkImage *get_image(IndicatorObject *object) { return ((UserMenu *)object)->image; }
static GtkMenu *get_menu(IndicatorObject *object) { return ((UserMenu *)object)->menu; }
static const gchar *get_desc(IndicatorObject *object)
{ return gtk_label_get_text(((UserMenu *)object)->label); }

static void activate(GtkMenuItem *item, gpointer command)
{
    (void)item;
    GError *error = NULL;
    if (!g_spawn_command_line_async(command, &error)) {
        g_warning("Unable to open user menu action: %s", error->message);
        g_error_free(error);
    }
}

static void action(UserMenu *self, const gchar *label, const gchar *command)
{
    GtkWidget *item = gtk_menu_item_new_with_label(label);
    g_signal_connect(item, "activate", G_CALLBACK(activate), (gpointer)command);
    gtk_menu_shell_append(GTK_MENU_SHELL(self->menu), item);
}

static void user_menu_class_init(UserMenuClass *klass)
{
    klass->get_label = get_label;
    klass->get_image = get_image;
    klass->get_menu = get_menu;
    klass->get_accessible_desc = get_desc;
}

static void user_menu_init(UserMenu *self)
{
    const gchar *name = g_get_real_name();
    if (!name || !*name || !g_strcmp0(name, "Unknown")) name = g_get_user_name();
    self->label = GTK_LABEL(gtk_label_new(name));
    self->image = GTK_IMAGE(gtk_image_new_from_icon_name("avatar-default-symbolic", GTK_ICON_SIZE_MENU));
    self->menu = GTK_MENU(gtk_menu_new());
    GtkWidget *current = gtk_check_menu_item_new_with_label(name);
    gtk_check_menu_item_set_active(GTK_CHECK_MENU_ITEM(current), TRUE);
    gtk_widget_set_sensitive(current, FALSE);
    gtk_menu_shell_append(GTK_MENU_SHELL(self->menu), current);
    gtk_menu_shell_append(GTK_MENU_SHELL(self->menu), gtk_separator_menu_item_new());
    action(self, "User Accounts…", "/usr/bin/gnome-control-center user-accounts");
    gtk_menu_shell_append(GTK_MENU_SHELL(self->menu), gtk_separator_menu_item_new());
    action(self, "Lock Screen", "/usr/bin/gnome-screensaver-command --lock");
    action(self, "Log Out…", "/usr/bin/gnome-session-quit --logout");
    gtk_widget_show_all(GTK_WIDGET(self->menu));
    gtk_widget_show(GTK_WIDGET(self->label));
    gtk_widget_show(GTK_WIDGET(self->image));
}

IndicatorObject *user_menu_new(void)
{ return g_object_new(user_menu_get_type(), NULL); }
