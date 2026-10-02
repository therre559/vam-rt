// Minimal stand-ins for the VaM / Unity API, used ONLY to compile-check the plugin outside VaM.
// Signatures mirror usages seen in the AcidBubbles Voxta plugin and VoxtaTouchElite.
using System;
using System.Collections;
using System.Collections.Generic;

namespace UnityEngine
{
    public struct Vector3
    {
        public float x, y, z;
        public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
        public static Vector3 up { get { return new Vector3(0, 1, 0); } }
        public static Vector3 forward { get { return new Vector3(0, 0, 1); } }
        public float magnitude { get { return (float)Math.Sqrt(x * x + y * y + z * z); } }
        public float sqrMagnitude { get { return x * x + y * y + z * z; } }
        public Vector3 normalized { get { float m = magnitude; return m > 1e-6f ? new Vector3(x / m, y / m, z / m) : new Vector3(0, 0, 0); } }
        public static Vector3 operator +(Vector3 a, Vector3 b) { return new Vector3(a.x + b.x, a.y + b.y, a.z + b.z); }
        public static Vector3 operator -(Vector3 a, Vector3 b) { return new Vector3(a.x - b.x, a.y - b.y, a.z - b.z); }
        public static Vector3 operator *(Vector3 a, float f) { return new Vector3(a.x * f, a.y * f, a.z * f); }
        public static float Dot(Vector3 a, Vector3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
        public static Vector3 Cross(Vector3 a, Vector3 b) { return new Vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x); }
        public static float Angle(Vector3 a, Vector3 b)
        {
            float d = Dot(a.normalized, b.normalized); d = Math.Max(-1f, Math.Min(1f, d));
            return (float)(Math.Acos(d) * 180.0 / Math.PI);
        }
        public static float Distance(Vector3 a, Vector3 b) { return (a - b).magnitude; }
    }
    public struct Quaternion
    {
        public float x, y, z, w;
        public static Quaternion AngleAxis(float angle, Vector3 axis)
        {
            float r = angle * (float)Math.PI / 360f; float s = (float)Math.Sin(r);
            Vector3 n = axis.normalized; Quaternion q; q.x = n.x * s; q.y = n.y * s; q.z = n.z * s; q.w = (float)Math.Cos(r); return q;
        }
        public static Vector3 operator *(Quaternion q, Vector3 v)
        {   // Unity convention: rotate v by q (left-handed, y-up); only the y-axis case is exercised by the plugin
            float a = 2f * (float)Math.Atan2(q.y, q.w); float c = (float)Math.Cos(a), s = (float)Math.Sin(a);
            return new Vector3(v.x * c + v.z * s, v.y, -v.x * s + v.z * c);
        }
    }
    public static class Mathf
    {
        public static float Abs(float f) { return Math.Abs(f); }
        public static float Max(float a, float b) { return Math.Max(a, b); }
        public static float Min(float a, float b) { return Math.Min(a, b); }
        public static int RoundToInt(float f) { return (int)Math.Round(f); }
    }
    public class Object { public string name; }
    public class Component : Object
    {
        private Transform _t; private GameObject _g;
        public Transform transform { get { if (_t == null) _t = (this as Transform) ?? new Transform(); return _t; } }
        public GameObject gameObject { get { if (_g == null) _g = new GameObject(); return _g; } }
        public T GetComponent<T>() { return default(T); }
    }
    public class GameObject : Object
    {
        private Transform _t;
        public Transform transform { get { if (_t == null) _t = new Transform(); return _t; } }
        public T GetComponent<T>() { return default(T); }
    }
    public class Transform : Component, IEnumerable
    {
        public Vector3 position, forward, right, up;
        public Transform Find(string n) { return null; }
        public IEnumerator GetEnumerator() { return new List<Transform>().GetEnumerator(); }
    }
    public class Camera : Component { }
    public class MonoBehaviour : Component { public Coroutine StartCoroutine(IEnumerator e) { return null; } }
    public class Coroutine { }
    public static class Time { public static float time; public static float deltaTime; }
}

public class JSONStorableString
{
    public string val; public string valNoCallback; public Action<string> setCallbackFunction;
    public JSONStorableString(string name, string startingValue) { val = startingValue; }
}
public class JSONStorableBool
{
    public bool val; public Action<bool> setCallbackFunction;
    public JSONStorableBool(string name, bool startingValue) { val = startingValue; }
}
public class JSONStorableFloat
{
    public float val; public Action<float> setCallbackFunction;
    public JSONStorableFloat(string name, float startingValue, float minValue, float maxValue, bool constrain = true, bool interactable = true) { val = startingValue; }
}
public class JSONStorableStringChooser
{
    public string val; public Action<string> setCallbackFunction;
    public JSONStorableStringChooser(string name, List<string> options, string startingValue, string displayName) { val = startingValue; }
}
public class JSONStorable : UnityEngine.MonoBehaviour
{
    public JSONStorableString GetStringJSONParam(string n) { return null; }
    public JSONStorableStringChooser GetStringChooserJSONParam(string n) { return null; }
    public string GetStringChooserParamValue(string n) { return ""; }
    public JSONStorableBool GetBoolJSONParam(string n) { return null; }
}
public class FreeControllerV3 : JSONStorable { }
public class MVRPluginManager : JSONStorable { }
public class Atom : UnityEngine.MonoBehaviour
{
    public string uid; public string type; public bool on; public FreeControllerV3 mainController;
    public JSONStorable GetStorableByID(string id) { return null; }
}
public class CameraTarget { public UnityEngine.Camera targetCamera; }
public class SuperController : UnityEngine.MonoBehaviour
{
    public static SuperController singleton;
    public CameraTarget centerCameraTarget;
    public List<Atom> GetAtoms() { return new List<Atom>(); }
    public Atom GetAtomByUid(string uid) { return null; }
    public IEnumerator AddAtomByType(string type, string uid = null) { yield break; }
    public void RemoveAtom(Atom a) { }
    public static void LogMessage(string s) { }
    public static void LogError(string s) { }
}
public class UIDynamic : UnityEngine.MonoBehaviour { public float height; }
public class UIDynamicTextField : UIDynamic { }
public class UIDynamicSlider : UIDynamic { }
public class UIDynamicToggle : UIDynamic { }
public class UIDynamicPopup : UIDynamic { }
public class UIDynamicButton : UIDynamic { public FakeButton button = new FakeButton(); }
public class FakeButton { public FakeEvent onClick = new FakeEvent(); }
public class FakeEvent { public void AddListener(Action a) { } }
public class MVRScript : JSONStorable
{
    public Atom containingAtom;
    public virtual void Init() { }
    public UIDynamicTextField CreateTextField(JSONStorableString s, bool rightSide = false) { return new UIDynamicTextField(); }
    public UIDynamicButton CreateButton(string label, bool rightSide = false) { return new UIDynamicButton(); }
    public UIDynamicSlider CreateSlider(JSONStorableFloat s, bool rightSide = false) { return new UIDynamicSlider(); }
    public UIDynamicToggle CreateToggle(JSONStorableBool s, bool rightSide = false) { return new UIDynamicToggle(); }
    public UIDynamicPopup CreateScrollablePopup(JSONStorableStringChooser s, bool rightSide = false) { return new UIDynamicPopup(); }
    public UIDynamic CreateSpacer(bool rightSide = false) { return new UIDynamic(); }
    public void RegisterBool(JSONStorableBool s) { }
    public void RegisterFloat(JSONStorableFloat s) { }
    public void RegisterString(JSONStorableString s) { }
    public void RegisterStringChooser(JSONStorableStringChooser s) { }
}
