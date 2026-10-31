#pragma once

#include <QMenu>
#include <QMouseEvent>
#include <QObject>

// A popup grabs pointer motion before the panel's QML buttons see it.
// Watch submenus too, so returning from a nested menu can switch headings.
class MenuHoverFilter : public QObject
{
    Q_OBJECT
public:
    using QObject::QObject;
    void watch(QMenu *menu) { menu->installEventFilter(this); }

Q_SIGNALS:
    void moved(const QPointF &globalPosition);

protected:
    bool eventFilter(QObject *watched, QEvent *event) override
    {
        if (qobject_cast<QMenu *>(watched) && event->type() == QEvent::MouseMove) {
            Q_EMIT moved(static_cast<QMouseEvent *>(event)->globalPosition());
        }
        return false;
    }
};
