import QtQuick

// Pixel-face seed entry. The shared Spin already stores its value as a JS
// number, so unlike Qt Quick Controls' 32-bit SpinBox it can carry Comfy's full
// safe-integer seed range.
Spin {
    id: seed
    from: -3
    to: 9007199254740992
    step: 1
}
