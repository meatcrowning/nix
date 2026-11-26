#include <QApplication>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QVBoxLayout>
#include <QDateTime>
#include <QIcon>
#include <QLabel>
#include <QListWidget>
#include <QProcess>
#include <QProcessEnvironment>
#include <QPushButton>
#include <QStyle>
#include <QTimer>
#include <cstdio>
#include <QUrl>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    app.setApplicationName("Dwarf Fortress Launcher");
    const bool check = app.arguments().contains("--check");
    if (check && app.platformName() != "offscreen")
        return 1;
    app.setWindowIcon(QIcon::fromTheme("applications-games"));

    const QDir runs(QDir::homePath() + "/.local/state/df-launcher/runs");
    QWidget window;
    window.setWindowTitle(app.applicationName());
    auto *layout = new QVBoxLayout(&window);
    auto *launch = new QPushButton("Play Dwarf Fortress with DFHack");
    auto *status = new QLabel;
    status->setWordWrap(true);
    auto *history = new QListWidget;
    auto *open = new QPushButton("Open Run Logs");
    open->setEnabled(false);
    layout->addWidget(launch);
    layout->addWidget(status);
    layout->addWidget(new QLabel("Recent runs"));
    layout->addWidget(history);
    layout->addWidget(open);

    QObject::connect(launch, &QPushButton::clicked, &window, [&] {
        QProcess steam;
        steam.setProgram("steam");
        steam.setArguments({"-applaunch", "975370"});
        auto environment = QProcessEnvironment::systemEnvironment();
        environment.remove("QT_PLUGIN_PATH");
        steam.setProcessEnvironment(environment);
        status->setText(steam.startDetached()
                            ? "Launch requested through Steam."
                            : "Could not start Steam.");
    });
    QObject::connect(history, &QListWidget::currentItemChanged, &window,
                     [open](QListWidgetItem *item) { open->setEnabled(item != nullptr); });
    QObject::connect(open, &QPushButton::clicked, &window, [&] {
        const auto name = history->currentItem()->data(Qt::UserRole).toString();
        if (!QDesktopServices::openUrl(QUrl::fromLocalFile(runs.filePath(name))))
            status->setText("Could not open the run directory.");
    });

    QStringList previousRows;
    const auto refresh = [&] {
        const auto folders = runs.entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot,
                                                QDir::Name | QDir::Reversed);
        QStringList rows;
        for (const auto &folder : folders) {
            QFile result(folder.filePath() + "/result.txt");
            const auto summary = result.open(QIODevice::ReadOnly)
                ? QString::fromUtf8(result.readLine()).trimmed()
                : QString("No exit recorded yet");
            rows.append(folder.fileName() + '\n' + summary);
        }
        if (rows == previousRows)
            return;
        previousRows = rows;
        const auto selected = history->currentItem()
            ? history->currentItem()->data(Qt::UserRole).toString()
            : QString();
        history->clear();
        for (qsizetype index = 0; index < folders.size(); ++index) {
            const auto key = folders[index].fileName();
            auto *item = new QListWidgetItem(
                folders[index].birthTime().toLocalTime().toString(Qt::ISODate)
                    + "  ·  " + rows[index].section('\n', 1), history);
            item->setData(Qt::UserRole, key);
            if (key == selected)
                history->setCurrentItem(item);
        }
        if (history->count() && !history->currentItem())
            history->setCurrentRow(0);
    };
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, &window, refresh);
    timer.start(2000);
    refresh();
    if (check) {
        std::puts(qPrintable(app.style()->objectName()));
        return 0;
    }
    window.resize(540, 330);
    window.show();
    return app.exec();
}
