#include "browsermenubridge.h"

#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QWebSocket>
#include <QWebSocketCorsAuthenticator>

namespace {
bool validItems(const QJsonArray &items, int depth, int &remaining)
{
    if (depth > 24) return false;
    for (const auto &value : items) {
        if (--remaining < 0 || !value.isObject()) return false;
        const auto item = value.toObject();
        if (item.value("label").toString().size() > 4096
            || item.value("id").toString().size() > 16384) return false;
        if (item.contains("children") && (!item.value("children").isArray()
            || !validItems(item.value("children").toArray(), depth + 1, remaining))) return false;
    }
    return true;
}
}

BrowserMenuBridge::BrowserMenuBridge(QObject *parent, quint16 port)
    : QObject(parent), m_server(QStringLiteral("Vivaldi Plasma menu"), QWebSocketServer::NonSecureMode, this)
{
    m_server.setMaxPendingConnections(8);
    connect(&m_server, &QWebSocketServer::originAuthenticationRequired, this,
        [](QWebSocketCorsAuthenticator *auth) {
            auth->setAllowed(auth->origin() == QStringLiteral("chrome-extension://mpognobbkildjkofajifpdfhcoklimli"));
        });
    connect(&m_server, &QWebSocketServer::newConnection, this, [this] {
        auto *socket = m_server.nextPendingConnection();
        if (!socket) return;
        socket->setParent(this);
        socket->setMaxAllowedIncomingMessageSize(4 * 1024 * 1024);
        socket->setMaxAllowedIncomingFrameSize(4 * 1024 * 1024);
        connect(socket, &QWebSocket::textMessageReceived, this, [this, socket](const QString &text) {
            const auto message = QJsonDocument::fromJson(text.toUtf8()).object();
            if (message.value("type") != "menus" || !message.value("menus").isArray()) return;
            if (m_selected && m_selected != socket && !message.value("active").toBool()) return;
            const auto items = message.value("menus").toArray();
            int remaining = 20000;
            if (!validItems(items, 0, remaining)) return;
            m_selected = socket;
            m_windowId = message.value("windowId").toInt(-1);
            m_title = message.value("title").toString();
            m_menus = items.toVariantList();
            Q_EMIT changed();
        });
        connect(socket, &QWebSocket::disconnected, this, [this, socket] {
            if (m_selected == socket) {
                m_selected = nullptr;
                m_menus.clear();
                m_title.clear();
                m_windowId = -1;
                Q_EMIT changed();
            }
            socket->deleteLater();
        });
    });
    if (!m_server.listen(QHostAddress::LocalHost, port))
        qWarning("Vivaldi menu bridge: cannot bind loopback port %u", port);
}

void BrowserMenuBridge::activate(int windowId, const QString &id)
{
    if (!m_selected || windowId != m_windowId || id.isEmpty()) return;
    m_selected->sendTextMessage(QString::fromUtf8(QJsonDocument(QJsonObject{
        {"type", "activate"}, {"windowId", windowId}, {"id", id}
    }).toJson(QJsonDocument::Compact)));
}
