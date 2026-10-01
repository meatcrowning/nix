// Use Steam's React instance: a second bundled copy breaks its navigation tree.
export default window.SP_REACT;
export const { createElement, useState, useEffect, useLayoutEffect, useRef, useMemo,
  useCallback, useContext, forwardRef, Fragment, Component, createContext,
  cloneElement, isValidElement } = window.SP_REACT;
