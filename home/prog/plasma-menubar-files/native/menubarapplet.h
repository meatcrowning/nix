#pragma once

#include <Plasma/Applet>

#include <QPointer>

class QMenu;
class QQuickItem;

class MenuBarApplet final : public Plasma::Applet
{
    Q_OBJECT

public:
    MenuBarApplet(QObject *parent, const KPluginMetaData &data, const QVariantList &args);

    Q_INVOKABLE void openMenu(QQuickItem *button, const QVariantList &entries);
    Q_INVOKABLE void closeMenu();

Q_SIGNALS:
    void menuTriggered(int index);
    void menuClosed();

private:
    QPointer<QMenu> m_menu;
};
