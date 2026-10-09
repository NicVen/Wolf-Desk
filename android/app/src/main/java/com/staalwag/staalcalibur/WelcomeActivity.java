package com.staalwag.staalcalibur;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

import com.google.androidbrowserhelper.trusted.LauncherActivity;

/** Native start screen. "Get Started" opens the live app (the website, full screen). */
public class WelcomeActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_welcome);
        findViewById(R.id.get_started).setOnClickListener(v -> {
            startActivity(new Intent(this, LauncherActivity.class));
            finish();
        });
    }
}
