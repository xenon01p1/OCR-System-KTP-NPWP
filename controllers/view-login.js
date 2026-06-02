// controllers/view-login.js

(function (window, $) {
    'use strict';

    const LOGIN_URL = 'controllers/auth-login.php';
    const CHECK_URL = 'controllers/auth-check.php';

    $(document).ready(function () {
        checkExistingSession();
        bindLoginEvents();
    });

    function checkExistingSession() {
        $.ajax({
            url: CHECK_URL,
            type: 'GET',
            dataType: 'json',
            success: function (response) {
                if (response && response.status === true && response.authenticated === true) {
                    window.location.href = 'index.html';
                }
            }
        });
    }

    function bindLoginEvents() {
        $(document).off('submit.loginForm', '#login-form');
        $(document).on('submit.loginForm', '#login-form', function (e) {
            e.preventDefault();
            submitLogin();
        });

        $(document).off('click.togglePassword', '#btn-toggle-password');
        $(document).on('click.togglePassword', '#btn-toggle-password', function () {
            const $password = $('#login-password');
            const isPassword = $password.attr('type') === 'password';

            $password.attr('type', isPassword ? 'text' : 'password');

            $(this).html(
                isPassword
                    ? '<i class="fa-regular fa-eye-slash"></i>'
                    : '<i class="fa-regular fa-eye"></i>'
            );
        });
    }

    function submitLogin() {
        const email = $('#login-email').val().trim();
        const password = $('#login-password').val();

        if (!email) {
            showAlert('warning', 'Email required', 'Please enter your email.');
            return;
        }

        if (!isValidEmail(email)) {
            showAlert('warning', 'Invalid email', 'Please enter a valid email address.');
            return;
        }

        if (!password) {
            showAlert('warning', 'Password required', 'Please enter your password.');
            return;
        }

        const $button = $('#btn-login');
        const originalHtml = $button.html();

        $button
            .prop('disabled', true)
            .addClass('opacity-70 cursor-not-allowed')
            .html('<i class="fa-solid fa-spinner fa-spin mr-2"></i>Checking...');

        $.ajax({
            url: LOGIN_URL,
            type: 'POST',
            dataType: 'json',
            data: {
                email: email,
                password: password
            },
            success: function (response) {
                if (!response || response.status !== true) {
                    showAlert(
                        'error',
                        'Login failed',
                        response && response.message ? response.message : 'Invalid login request.'
                    );
                    return;
                }

                window.location.href = 'index.html';
            },
            error: function (xhr) {
                showAlert('error', 'Login failed', getAjaxErrorMessage(xhr));
            },
            complete: function () {
                $button
                    .prop('disabled', false)
                    .removeClass('opacity-70 cursor-not-allowed')
                    .html(originalHtml);
            }
        });
    }

    function isValidEmail(email) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    }

    function getAjaxErrorMessage(xhr) {
        if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
            return xhr.responseJSON.message;
        }

        if (xhr && xhr.responseText) {
            try {
                const parsed = JSON.parse(xhr.responseText);

                if (parsed.message) {
                    return parsed.message;
                }
            } catch (e) {
                return xhr.responseText.substring(0, 150);
            }
        }

        return 'Request failed.';
    }

    function showAlert(icon, title, text) {
        Swal.fire({
            icon: icon,
            title: title,
            text: text,
            confirmButtonColor: '#4f46e5'
        });
    }

})(window, jQuery);