#include "browsermenubridge.h"
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTest>
#include <QWebSocket>

class BridgeTest : public QObject {
    Q_OBJECT
private Q_SLOTS:
    void protocol() {
        BrowserMenuBridge bridge(nullptr, 0);
        QVERIFY(bridge.listening());
        const QUrl url(QStringLiteral("ws://127.0.0.1:%1").arg(bridge.port()));
        QWebSocket rejected(QStringLiteral("https://example.com"));
        QSignalSpy rejectedError(&rejected, &QWebSocket::errorOccurred);
        QSignalSpy rejectedConnected(&rejected, &QWebSocket::connected);
        rejected.open(url);
        QTRY_COMPARE(rejectedError.size(), 1);
        QCOMPARE(rejectedConnected.size(), 0);
        QVERIFY(bridge.menus().isEmpty());
        QWebSocket browser(QStringLiteral("chrome-extension://mpognobbkildjkofajifpdfhcoklimli"));
        QSignalSpy connected(&browser, &QWebSocket::connected);
        QSignalSpy replies(&browser, &QWebSocket::textMessageReceived);
        browser.open(url);
        QTRY_COMPARE(connected.size(), 1);
        browser.sendTextMessage(R"({"type":"menus","windowId":42,"title":"Example","active":true,"menus":[{"label":"File","children":[{"label":"New Tab","id":"new"}]}]})");
        QTRY_COMPARE(bridge.title(), QStringLiteral("Example"));
        QCOMPARE(bridge.menus().size(), 1);
        bridge.activate(41, "new");
        bridge.activate(42, "");
        QCOMPARE(replies.size(), 0);
        bridge.activate(42, "new");
        QTRY_COMPARE(replies.size(), 1);
        const auto reply = QJsonDocument::fromJson(replies.at(0).at(0).toString().toUtf8()).object();
        QCOMPARE(reply.value("windowId").toInt(), 42);
        QCOMPARE(reply.value("id").toString(), QStringLiteral("new"));
        browser.sendTextMessage(R"({"type":"menus","menus":[{"children":"bad"}]})");
        QTest::qWait(50);
        QCOMPARE(bridge.title(), QStringLiteral("Example"));
        QWebSocket second(QStringLiteral("chrome-extension://mpognobbkildjkofajifpdfhcoklimli"));
        QSignalSpy secondConnected(&second, &QWebSocket::connected);
        second.open(url);
        QTRY_COMPARE(secondConnected.size(), 1);
        second.sendTextMessage(R"({"type":"menus","windowId":43,"title":"Other","active":false,"menus":[]})");
        QTest::qWait(50);
        QCOMPARE(bridge.windowId(), 42);
        second.sendTextMessage(R"({"type":"menus","windowId":43,"title":"Other","active":true,"menus":[]})");
        QTRY_COMPARE(bridge.windowId(), 43);
        browser.close();
        QTest::qWait(50);
        QCOMPARE(bridge.windowId(), 43);
        second.close();
        QTRY_COMPARE(bridge.windowId(), -1);
        QVERIFY(bridge.menus().isEmpty());
    }
};
QTEST_GUILESS_MAIN(BridgeTest)
#include "bridge-test.moc"
