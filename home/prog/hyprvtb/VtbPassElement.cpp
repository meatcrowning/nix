#include "VtbPassElement.hpp"
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include "vtbDeco.hpp"

using namespace Render::GL;

CVtbPassElement::CVtbPassElement(const CVtbPassElement::SVtbData& data_) : data(data_) {
    ;
}

std::vector<UP<IPassElement>> CVtbPassElement::draw() {
    if (data.tooltipOnly)
        data.deco->drawTooltipPass(g_pHyprRenderer->m_renderData.pMonitor.lock(), data.a);
    else
        data.deco->renderPass(g_pHyprRenderer->m_renderData.pMonitor.lock(), data.a);
    return {};
}

bool CVtbPassElement::needsLiveBlur() {
    return false;
}

bool CVtbPassElement::needsPrecomputeBlur() {
    return false;
}

std::optional<CBox> CVtbPassElement::boundingBox() {
    // Tooltip-only element (RENDER_POST_WINDOWS): just the label box, which
    // mainThreadTick pre-sizes generously the moment the tooltip is shown so
    // this box already covers the strip on the very first frame (before
    // renderTooltip has computed the exact box). If it's not shown / not sized
    // yet, claim nothing.
    if (data.tooltipOnly) {
        const auto& t = data.deco->m_tooltipBox;
        if (!data.deco->m_bTooltipShown || t.w <= 0)
            return std::nullopt;
        return CBox{t}.translate(-g_pHyprRenderer->m_renderData.pMonitor->m_position).expand(4);
    }

    CBox box = data.deco->effectiveBoxGlobal();
    return box.translate(-g_pHyprRenderer->m_renderData.pMonitor->m_position).expand(4);
}
