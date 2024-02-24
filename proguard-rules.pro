# Add project-specific ProGuard rules here.
# By default, Android projects use the ProGuard rules from the Android SDK.

# Keep the class names of your application's entry points (e.g., Activities, Services, BroadcastReceiver)
-keep public class com.example.myapp.MainActivity
-keep public class com.example.myapp.MyService
-keep public class com.example.myapp.MyBroadcastReceiver

# Keep classes that are used in your XML layout files (e.g., custom views)
-keep public class com.example.myapp.customviews.**

# Keep the names of any classes that are used in reflection or JNI
-keepclassmembers class com.example.myapp.** {
    *;
}

# Keep all classes in the androidx.appcompat package to avoid errors with AppCompat
-keep class androidx.appcompat.** { *; }

# Keep the Retrofit interfaces and their methods
-keep interface retrofit2.** { *; }
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}

# Keep the GSON classes and fields
-keep class com.google.gson.** { *; }
-keep class com.google.gson.examples.android.model.** { *; }
-keepattributes Signature
-keepattributes *Annotation*

# Keep the Jackson classes and fields
-keep class com.fasterxml.jackson.databind.ObjectMapper {
    <init>(...);
}
-keepnames class com.fasterxml.jackson.** { *; }
-keepnames interface com.fasterxml.jackson.** { *; }
-keepclassmembers class com.fasterxml.jackson.** {
    *;
}

# Add any other custom ProGuard rules specific to your app here