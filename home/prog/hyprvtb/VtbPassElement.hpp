#pragma once
#include <hyprland/src/render/pass/PassElement.hpp>

class CVtbDeco;

class CVtbPassElement : public IPassElement {
  public:
    struct SVtbData {
        CVtbDeco* deco = nullptr;
        float     a    = 1.F;
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
