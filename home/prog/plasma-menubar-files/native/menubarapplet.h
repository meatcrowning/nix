#pragma once

#include <Plasma/Applet>

#include <QPointer>

class BrowserMenuBridge;
class QMenu;
class QQuickItem;

class MenuBarApplet final : public Plasma::Applet
{
    Q_OBJECT
    Q_PROPERTY(QVariantList browserMenus READ browserMenus NOTIFY browserMenusChanged)
    Q_PROPERTY(QString browserTitle READ browserTitle NOTIFY browserMenusChanged)

public:
    MenuBarApplet(QObject *parent, const KPluginMetaData &data, const QVariantList &args);

    Q_INVOKABLE void openMenu(QQuickItem *button, const QVariantList &entries);
    Q_INVOKABLE void closeMenu();
    QVariantList browserMenus() const;
    QString browserTitle() const;

Q_SIGNALS:
    void browserMenusChanged();
    void menuTriggered(int index);
    void menuClosed();

private:
    QPointer<QMenu> m_menu;
    BrowserMenuBridge *m_bridge;
};
