#pragma once
#include <hyprland/src/render/pass/PassElement.hpp>

class CVtbDeco;

class CVtbPassElement : public IPassElement {
  public:
    struct SVtbData {
        CVtbDeco* deco = nullptr;
        float     a    = 1.F;
        // A tooltip-only element: enqueued at RENDER_POST_WINDOWS so the hover
        // label draws OVER the window surface. The bar itself is a normal
        // UNDER-layer element (deco draws before the window) — fine for the bar,
        // which lives in reserved space to the right, but the tooltip pops out
        // LEFT into the window's area and would be painted over there.
        bool tooltipOnly = false;
    };

    CVtbPassElement(const SVtbData& data_);
    virtual ~CVtbPassElement() = default;

    virtual std::vector<UP<IPassElement>> draw() override;
    virtual bool                          needsLiveBlur() override;
    virtual bool                          needsPrecomputeBlur() override;
    virtual std::optional<CBox>           boundingBox() override;

    virtual const char*                   passName() override {
        return "CVtbPassElement";
    }

    virtual ePassElementType type() override {
        return EK_CUSTOM;
    }

  private:
    SVtbData data;
};
