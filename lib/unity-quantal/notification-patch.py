"""Keep Quantal's bubble renderer, with dynamic placement and real actions."""
from pathlib import Path


def replace(file, old, new, count=1):
    path = Path('src') / file
    text = path.read_text()
    assert text.count(old) == count, (file, old, text.count(old))
    path.write_text(text.replace(old, new))


replace('defaults.c', 'self->slot_allocation = SLOT_ALLOCATION_FIXED;',
        'self->slot_allocation = SLOT_ALLOCATION_DYNAMIC;')
replace('stack.c', 'turn_into_dialog = dialog_check_actions_and_timeout (actions, timeout);',
        'turn_into_dialog = FALSE;')
replace('stack.c', '\tif (summary)\n', '''\tg_object_set_data_full(G_OBJECT(bubble), "default-action", NULL, g_free);
    if (actions) for (guint i = 0; actions[i] && actions[i + 1]; i += 2)
        if (!strcmp(actions[i], "default"))
            g_object_set_data_full(G_OBJECT(bubble), "default-action", g_strdup("default"), g_free);

\tif (summary)
''')
replace('stack.c', '\t//bubble_hide (bubble);\n\t//g_object_unref (bubble);\n\t//stack_layout (self);',
        '\tbubble_clear_timer (bubble);\n\tbubble_hide (bubble);\n\tclose_handler (G_OBJECT(bubble), self);')
replace('bubble.c', 'static\nvoid\nupdate_input_shape (GtkWidget* window)',
        '#include "notification-interaction.c"\n\nstatic\nvoid\nupdate_input_shape (GtkWidget* window)')
replace('bubble.c', '\t// set an 1x1 input-region to allow click-through', '''\tBubble *bubble = g_object_get_data(G_OBJECT(window), "bubble");
    if (bubble && interactive(bubble)) {
        gtk_widget_input_shape_combine_region(window, NULL);
        return;
    }
\t// set an 1x1 input-region to allow click-through''')
replace('bubble.c', '\tcairo_destroy (cr);\n\n\t_set_bg_blur', '\tdraw_close(bubble, cr);\n\tcairo_destroy (cr);\n\n\t_set_bg_blur')
replace('bubble.c', '\t\t// mark mouse-pointer having left bubble and proximity-area',
        '\t\tupdate_input_shape(window);\n\t\tif (interactive(bubble)) priv->distance = 1.0f;\n\n\t\t// mark mouse-pointer having left bubble and proximity-area')
replace('bubble.c', 'if (bubble_is_mouse_over (bubble))',
        'if (bubble_is_mouse_over (bubble) && !interactive(bubble))', count=2)
replace('bubble.c', '\tg_object_set_data (G_OBJECT(window), "bubble", (gpointer) this);',
        '''\tg_object_set_data (G_OBJECT(window), "bubble", (gpointer) this);
    gtk_widget_add_events(window, GDK_BUTTON_RELEASE_MASK);
    g_signal_connect(window, "button-release-event", G_CALLBACK(clicked), this);''')
# GCC now rejects pointer constants used as integer GTypes in this old source.
replace('bubble-window.c', 'GType derived_type = NULL;', 'GType derived_type = 0;')
replace('bubble-window.c', 'GType derived_atk_type = NULL;', 'GType derived_atk_type = 0;')
replace('bubble.c', 'if (bubble_is_mouse_over (self))',
        'if (bubble_is_mouse_over (self) && !interactive(self))')
replace('bubble.c', '\t\t\tpriv->title_height = _calc_title_height (',
        '\t\t\tif (!bubble_is_synchronous(self)) priv->title_width -= 24;\n\t\t\tpriv->title_height = _calc_title_height (', count=4)
