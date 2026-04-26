"""Authentication blueprint: register, login, logout, email verify, password reset."""

from datetime import datetime, timezone

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from app import db
from app.auth.forms import (LoginForm, PasswordResetForm,
                             PasswordResetRequestForm, ProfileUpdateForm,
                             RegistrationForm)
from app.models import AuditAction, AuditLog, User, UserRole
from app.utils.audit import log_action
from app.utils.email import send_email_verification, send_password_reset_email
from app.utils.file_handler import save_uploaded_file
from app.utils.security import generate_token, verify_token

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            name=form.name.data.strip(),
            email=form.email.data.lower().strip(),
            role=UserRole(form.role.data),
            organization=form.organization.data.strip(),
            phone=form.phone.data,
            gst_number=form.gst_number.data,
            address=form.address.data,
        )
        user.set_password(form.password.data)

        # Handle digital signature upload
        if form.digital_signature.data:
            sig_path = save_uploaded_file(
                form.digital_signature.data,
                subfolder='signatures',
                allowed_extensions={'png', 'jpg', 'jpeg', 'pdf'}
            )
            if sig_path:
                user.digital_signature = sig_path
                user.signature_verified = True  # Mock: auto-verify on upload

        # Generate email verification token
        token = generate_token(user.email, salt='email-verification')
        user.email_verify_token = token
        user.email_verify_sent_at = datetime.now(timezone.utc)

        db.session.add(user)
        db.session.commit()

        # Send verification email (non-blocking)
        try:
            send_email_verification(user, token)
        except Exception as e:
            current_app.logger.warning(f'Email send failed: {e}')

        log_action(AuditAction.USER_REGISTER, user_id=user.id,
                   resource_type='user', resource_id=user.id,
                   description=f'New {user.role.value} registered: {user.email}')

        flash('Registration successful! Please check your email to verify your account.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    email = verify_token(token, salt='email-verification',
                         max_age=current_app.config['TOKEN_EXPIRY_HOURS'] * 3600)
    if not email:
        flash('Verification link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if user.email_verified:
        flash('Email already verified. Please log in.', 'info')
        return redirect(url_for('auth.login'))

    user.email_verified = True
    user.is_active = True
    user.email_verify_token = None
    db.session.commit()

    log_action(AuditAction.USER_EMAIL_VERIFY, user_id=user.id,
               resource_type='user', resource_id=user.id,
               description=f'Email verified: {user.email}')

    flash('Email verified successfully! You can now log in.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        if not user or not user.check_password(form.password.data):
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', form=form)

        if not user.email_verified:
            flash('Please verify your email before logging in.', 'warning')
            return render_template('auth/login.html', form=form)

        if user.is_suspended:
            flash('Your account has been suspended. Contact the administrator.', 'danger')
            return render_template('auth/login.html', form=form)

        login_user(user, remember=form.remember_me.data)
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()

        log_action(AuditAction.USER_LOGIN, user_id=user.id,
                   resource_type='user', resource_id=user.id,
                   description=f'User logged in: {user.email}',
                   ip_address=request.remote_addr)

        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('main.dashboard')
        return redirect(next_page)

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    log_action(AuditAction.USER_LOGOUT, user_id=current_user.id,
               resource_type='user', resource_id=current_user.id,
               description=f'User logged out: {current_user.email}')
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = PasswordResetRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            token = generate_token(user.email, salt='password-reset')
            user.password_reset_token = token
            user.password_reset_sent_at = datetime.now(timezone.utc)
            db.session.commit()
            try:
                send_password_reset_email(user, token)
            except Exception as e:
                current_app.logger.warning(f'Password reset email failed: {e}')

        # Always show success to prevent email enumeration
        flash('If that email is registered, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    email = verify_token(token, salt='password-reset',
                         max_age=current_app.config['TOKEN_EXPIRY_HOURS'] * 3600)
    if not email:
        flash('Password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = PasswordResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.password_reset_token = None
        db.session.commit()

        log_action(AuditAction.USER_PASSWORD_RESET, user_id=user.id,
                   resource_type='user', resource_id=user.id,
                   description=f'Password reset: {user.email}')

        flash('Password reset successfully. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form, token=token)


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileUpdateForm(obj=current_user)
    if form.validate_on_submit():
        current_user.name = form.name.data.strip()
        current_user.organization = form.organization.data
        current_user.phone = form.phone.data
        current_user.address = form.address.data
        current_user.gst_number = form.gst_number.data
        current_user.pan_number = form.pan_number.data

        if form.digital_signature.data:
            sig_path = save_uploaded_file(
                form.digital_signature.data,
                subfolder='signatures',
                allowed_extensions={'png', 'jpg', 'jpeg', 'pdf'}
            )
            if sig_path:
                current_user.digital_signature = sig_path
                current_user.signature_verified = True

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', form=form)
