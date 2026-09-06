#include "menubarapplet.h"

#include <KPluginFactory>

#include <QAction>
#include <QGuiApplication>
#include <QMenu>
#include <QQuickItem>
#include <QQuickWindow>
#include <QScreen>
#include <QWindow>

K_PLUGIN_CLASS_WITH_JSON(MenuBarApplet, "metadata.json")

MenuBarApplet::MenuBarApplet(QObject *parent, const KPluginMetaData &data, const QVariantList &args)
    : Plasma::Applet(parent, data, args)
{
}

void MenuBarApplet::closeMenu()
{
    if (m_menu) {
        m_menu->close();
    }
}

void MenuBarApplet::openMenu(QQuickItem *button, const QVariantList &entries)
{
    if (!button || !button->window() || entries.isEmpty()) {
        return;
    }

    closeMenu();
    auto *menu = new QMenu;
    m_menu = menu;
    connect(menu, &QMenu::aboutToHide, this, [this, menu] {
        if (m_menu == menu) {
            m_menu = nullptr;
        }
        Q_EMIT menuClosed();
        menu->deleteLater();
    });

    for (int index = 0; index < entries.size(); ++index) {
        const QVariantMap entry = entries.at(index).toMap();
        if (entry.value(QStringLiteral("separator")).toBool()) {
            menu->addSeparator();
            continue;
        }
        QAction *action = menu->addAction(entry.value(QStringLiteral("label")).toString());
        action->setEnabled(entry.value(QStringLiteral("enabled"), true).toBool());
        action->setCheckable(entry.value(QStringLiteral("checked")).toBool());
        action->setChecked(entry.value(QStringLiteral("checked")).toBool());
        connect(action, &QAction::triggered, this, [this, index] { Q_EMIT menuTriggered(index); });
    }

    menu->adjustSize();
    const QPoint origin = button->window()->mapToGlobal(
        button->mapToScene(QPointF(0, button->height())).toPoint());
    const QRect bounds = button->window()->screen()->availableVirtualGeometry();
    const QPoint position(qBound(bounds.left(), origin.x(), bounds.right() - menu->width() + 1),
                          qBound(bounds.top(), origin.y(), bounds.bottom() - menu->height() + 1));
    menu->setAttribute(Qt::WA_TranslucentBackground);
    menu->winId();
    menu->windowHandle()->setTransientParent(button->window());
    menu->popup(position);
}

#include "menubarapplet.moc"
