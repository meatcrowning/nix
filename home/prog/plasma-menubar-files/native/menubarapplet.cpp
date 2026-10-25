#include "menubarapplet.h"
#include "browsermenubridge.h"
#include <functional>

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
    static QPointer<BrowserMenuBridge> bridge;
    if (!bridge) bridge = new BrowserMenuBridge(qApp);
    m_bridge = bridge;
    connect(m_bridge, &BrowserMenuBridge::changed, this, &MenuBarApplet::browserMenusChanged);
}

QVariantList MenuBarApplet::browserMenus() const { return m_bridge->menus(); }
QString MenuBarApplet::browserTitle() const { return m_bridge->title(); }

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

    const int browserWindow = m_bridge->windowId();
    std::function<void(QMenu *, const QVariantList &)> populate;
    populate = [this, &populate, browserWindow](QMenu *parent, const QVariantList &items) {
        for (int index = 0; index < items.size(); ++index) {
            const QVariantMap entry = items.at(index).toMap();
            if (entry.value("separator").toBool()) { parent->addSeparator(); continue; }
            // Browser labels contain literal ampersands, not Qt mnemonics.
            QString label = entry.value("label").toString();
            if (entry.value("browser").toBool()) label.replace("&", "&&");
            if (entry.contains("children")) {
                auto *child = parent->addMenu(label);
                child->setEnabled(entry.value("enabled", true).toBool());
                populate(child, entry.value("children").toList());
                continue;
            }
            const QString shortcut = entry.value("shortcut").toString();
            if (!shortcut.isEmpty()) label += '\t' + shortcut;
            QAction *action = parent->addAction(label);
            action->setEnabled(entry.value("enabled", true).toBool());
            action->setCheckable(entry.value("checkable").toBool() || entry.value("checked").toBool());
            action->setChecked(entry.value("checked").toBool());
            const QString id = entry.value("id").toString();
            connect(action, &QAction::triggered, this, [this, index, id, browserWindow] {
                if (!id.isEmpty()) m_bridge->activate(browserWindow, id);
                else Q_EMIT menuTriggered(index);
            });
        }
    };
    populate(menu, entries);

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
