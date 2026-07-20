#include "VtbPassElement.hpp"
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include "vtbDeco.hpp"

using namespace Render::GL;

CVtbPassElement::CVtbPassElement(const CVtbPassElement::SVtbData& data_) : data(data_) {
    ;
}

std::vector<UP<IPassElement>> CVtbPassElement::draw() {
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
    return data.deco->effectiveBoxGlobal().translate(-g_pHyprRenderer->m_renderData.pMonitor->m_position).expand(4);
}
