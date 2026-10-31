#include "menuhoverfilter.h"
#include <QApplication>
#include <QSignalSpy>
#include <QTest>

class MenuHoverTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void grabbedMotion()
    {
        QCOMPARE(QApplication::platformName(), QStringLiteral("offscreen"));
        MenuHoverFilter filter;
        QMenu root;
        QMenu *child = root.addMenu("Nested");
        filter.watch(&root);
        filter.watch(child);
        QSignalSpy motion(&filter, &MenuHoverFilter::moved);
        // The pointer is above the popup, over a panel heading. Local popup
        // coordinates are negative; consumers need the global coordinates.
        for (QMenu *menu : {&root, child}) {
            QMouseEvent event(QEvent::MouseMove, QPointF(20, -15), QPointF(340, 12),
                              Qt::NoButton, Qt::NoButton, Qt::NoModifier);
            QApplication::sendEvent(menu, &event);
        }
        QCOMPARE(motion.count(), 2);
        QCOMPARE(motion.at(0).at(0).toPointF(), QPointF(340, 12));
        QCOMPARE(motion.at(1).at(0).toPointF(), QPointF(340, 12));
        // Removing a watched submenu must not leave a dangling receiver.
        root.clear();
        QEvent leave(QEvent::Leave);
        QApplication::sendEvent(&root, &leave);
        QCOMPARE(motion.count(), 2);
    }
};
QTEST_MAIN(MenuHoverTest)
#include "menu-hover-test.moc"
