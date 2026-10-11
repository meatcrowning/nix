/* The timer owns its image until dispatch completes. Navigating away releases
 * the image data and stops playback, including a pending final dispatch. */
static gboolean
private_timeout (gpointer data)
{
    EogImage *img = EOG_IMAGE (data);
    EogImagePrivate *priv = img->priv;
    if (!eog_image_is_animation (img) || !priv->is_playing ||
        g_source_is_destroyed (g_main_current_source ())) {
        priv->is_playing = FALSE;
        return FALSE;
    }
    /* An early timer must not busy-wait for the next frame. */
    eog_image_iter_advance (img);
    if (priv->anim_iter && priv->is_playing) {
        gint delay = gdk_pixbuf_animation_iter_get_delay_time (priv->anim_iter);
        if (delay >= 0) {
            g_timeout_add_full (G_PRIORITY_DEFAULT, MAX (10, delay), private_timeout,
                                g_object_ref (img), g_object_unref);
            return FALSE;
        }
    }
    priv->is_playing = FALSE;
    return FALSE;
}
