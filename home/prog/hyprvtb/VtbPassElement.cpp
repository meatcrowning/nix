#include "VtbPassElement.hpp"
#include "vtbDeco.hpp" // -> vtbCompat.hpp, the one place naming Hyprland internals

CVtbPassElement::CVtbPassElement(const CVtbPassElement::SVtbData& data_) : data(data_) {
    ;
}

std::vector<UP<IPassElement>> CVtbPassElement::draw() {
    if (data.shadowLayer)
        vtbRenderShadowLayer(Hl::renderMonitor(), data.shadowOverBars);
    else if (data.tooltipOnly)
        data.deco->drawTooltipPass(Hl::renderMonitor(), data.a);
    else
        data.deco->renderPass(Hl::renderMonitor(), data.a);
    return {};
}

bool CVtbPassElement::needsLiveBlur() {
    return false;
}

bool CVtbPassElement::needsPrecomputeBlur() {
    return false;
}

std::optional<CBox> CVtbPassElement::boundingBox() {
    // The shadow layer spans the whole monitor (it draws every window's shadow);
    // nullopt = "unknown", which keeps it out of the pass's occlusion
    // simplification instead of claiming a box it would then be culled against.
    if (data.shadowLayer)
        return std::nullopt;

    // Tooltip-only element (RENDER_POST_WINDOWS): just the label box, which
    // mainThreadTick pre-sizes generously the moment the tooltip is shown so
    // this box already covers the strip on the very first frame (before
    // renderTooltip has computed the exact box). If it's not shown / not sized
    // yet, claim nothing.
    if (data.tooltipOnly) {
        const auto& t = data.deco->m_tooltipBox;
        if (!data.deco->m_bTooltipShown || t.w <= 0)
            return std::nullopt;
        return CBox{t}.translate(-Hl::renderMonitorPos()).expand(4);
    }

    CBox box = data.deco->effectiveBoxGlobal();
    return box.translate(-Hl::renderMonitorPos()).expand(4);
}
