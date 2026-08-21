/*
    kwin-momentum — plugin entry point.

    A KWin::Plugin (binary compositor extension) that installs the
    MomentumFilter into the input chain at construction. Registered through the
    standard KWin PluginFactory interface (plugin.h): the factory IID carries
    the compositor version (PluginFactory_iid == "…PluginFactoryInterface6.7.4"),
    which is precisely why this .so is recompile-only on every KWin bump — see
    docs/agents/kwin-momentum-plugin-runbook.md.

    The artifact installs to a USER plugin dir
    (~/.local/lib64/qt6/plugins/kwin/plugins/) with QT_PLUGIN_PATH exported for
    the Plasma session; no root for the artifact itself. It is NOT loaded by
    this build step — the user enables and loads it in his own session.
*/
#include "momentumfilter.h"

#include <plugin.h>
#include <input.h>

#include <memory>

namespace KWinMomentum
{

class MomentumPlugin : public KWin::Plugin
{
    Q_OBJECT

public:
    MomentumPlugin()
    {
        m_filter = std::make_unique<MomentumFilter>();
        KWin::input()->installInputEventFilter(m_filter.get());
    }

    ~MomentumPlugin() override
    {
        if (m_filter) {
            KWin::input()->uninstallInputEventFilter(m_filter.get());
        }
    }

private:
    std::unique_ptr<MomentumFilter> m_filter;
};

class MomentumPluginFactory : public KWin::PluginFactory
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID PluginFactory_iid FILE "metadata.json")
    Q_INTERFACES(KWin::PluginFactory)

public:
    std::unique_ptr<KWin::Plugin> create() const override
    {
        return std::make_unique<MomentumPlugin>();
    }
};

} // namespace KWinMomentum

#include "main.moc"
