#pragma once

#include <QObject>
#include <QPointer>
#include <QVariantList>
#include <QWebSocketServer>

class QWebSocket;

// One loopback listener per shell, shared by panel applet instances. Only the
// packaged Vivaldi UI origin is accepted; ordinary websites cannot connect.
class BrowserMenuBridge final : public QObject
{
    Q_OBJECT
public:
    explicit BrowserMenuBridge(QObject *parent = nullptr, quint16 port = 19191);
    QVariantList menus() const { return m_menus; }
    QString title() const { return m_title; }
    int windowId() const { return m_windowId; }
    bool listening() const { return m_server.isListening(); }
    quint16 port() const { return m_server.serverPort(); }
    void activate(int windowId, const QString &id);
Q_SIGNALS:
    void changed();
private:
    QWebSocketServer m_server;
    QPointer<QWebSocket> m_selected;
    QVariantList m_menus;
    QString m_title;
    int m_windowId = -1;
};
